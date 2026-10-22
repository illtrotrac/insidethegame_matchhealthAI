// Match Health AI — cost-lean Azure footprint (scale to zero, free tiers).
//
// This mirrors what's actually deployed in `matchhealth-rg` for the hackathon
// build (see CLAUDE.md "Deployed resources"), which was provisioned ad hoc via
// `az` CLI for speed during the build. This file documents that topology and
// should deploy an equivalent stack into a fresh resource group, but it has
// NOT been freshly validated end to end with `az deployment group create`
// against a clean subscription -- treat it as an accurate reference, verify
// before relying on it for a from-scratch deploy. A few things worth knowing
// if you do run it:
//   - Cosmos DB free tier is one per subscription; enableFreeTier will fail
//     if another account already claims it there.
//   - gpt-4.1-nano had 0 default GlobalStandard quota on the subscription
//     this was built against; foundryDeploymentNano defaults to the mini
//     deployment name as a workaround (see CLAUDE.md). Point it at a real
//     nano deployment once quota is approved.
//   - The negotiate app's command avoids `-m` deliberately matched a bug in
//     the `az containerapp create --command` CLI parser (any token starting
//     with `-` confused its arg parsing), not an ARM/Bicep limitation --
//     `["python", "-m", "matchhealth.negotiate_service"]` would be fine here,
//     but the script-path form is kept for parity with what's actually live.
targetScope = 'resourceGroup'

param location string = resourceGroup().location
param prefix string = 'matchhealth'
param foundryDeploymentMini string = 'gpt-4.1-mini'
param foundryDeploymentNano string = 'gpt-4.1-mini' // see note above
param replayImage string = 'ghcr.io/illtrotrac/matchhealthai:latest'

// Built-in role definition IDs used below (same ones granted via `az role
// assignment create` / `az cosmosdb sql role assignment create` during the
// actual deploy).
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var webPubSubServiceOwnerRoleId = '12cf5a90-567b-43ae-8102-96cf46c7d9b4'
var cosmosDataContributorRoleId = '00000000-0000-0000-0000-000000000002' // Cosmos SQL built-in role, not an Authorization roleDefinition

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs'
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-ai'
  location: location
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id }
}

// Microsoft Foundry project (Cognitive Services AIServices kind) + one model
// deployment. Pay-per-token GlobalStandard: $0 while idle.
resource foundry 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: '${prefix}-foundry'
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: { customSubDomainName: '${prefix}-foundry' }
}

resource foundryMini 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: foundry
  name: foundryDeploymentMini
  sku: { name: 'GlobalStandard', capacity: 50 } // 50K TPM: 10K was not enough to absorb a burst of ~45 triggers' worth of calls without rate-limit timeouts
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4.1-mini', version: '2025-04-14' }
  }
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: '${prefix}-cosmos'
  location: location
  properties: {
    databaseAccountOfferType: 'Standard'
    enableFreeTier: true // one free-tier account per subscription
    locations: [ { locationName: location } ]
    disableLocalAuth: false
  }
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmos
  name: 'matchhealth'
  properties: { resource: { id: 'matchhealth' } }
}

resource cosmosContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosDb
  name: 'moments'
  properties: {
    resource: {
      id: 'moments'
      partitionKey: { paths: [ '/match_id' ], kind: 'Hash' }
    }
    options: { throughput: 1000 } // within the free-tier allowance
  }
}

resource pubsub 'Microsoft.SignalRService/webPubSub@2024-03-01' = {
  name: '${prefix}-pubsub'
  location: location
  sku: { name: 'Free_F1', capacity: 1 }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

// Issues short-lived Web PubSub client tokens to the browser at /negotiate.
// Scale-to-zero Consumption plan: $0 while idle.
resource negotiateApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-negotiate'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    environmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: 8080 }
    }
    template: {
      containers: [ {
        name: '${prefix}-negotiate'
        image: replayImage
        command: [ 'python', '/app/src/matchhealth/negotiate_service.py' ]
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
        env: [
          { name: 'WEBPUBSUB_ENDPOINT', value: 'https://${pubsub.properties.hostName}' }
          { name: 'WEBPUBSUB_HUB', value: 'overlays' }
          { name: 'PORT', value: '8080' }
        ]
      } ]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

// Replay + crew run as an on-demand job: billed only while a match replays.
// replicaTimeout covers a full real-time (speed=1) 90-minute match.
resource replayJob 'Microsoft.App/jobs@2024-03-01' = {
  name: '${prefix}-replay'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 6000
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
    }
    template: {
      containers: [ {
        name: 'replay'
        image: replayImage
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'MATCHHEALTH_MOCK_LLM', value: '0' }
          { name: 'FOUNDRY_ENDPOINT', value: foundry.properties.endpoint }
          { name: 'FOUNDRY_API_VERSION', value: '2024-10-21' }
          { name: 'FOUNDRY_DEPLOYMENT_MINI', value: foundryDeploymentMini }
          { name: 'FOUNDRY_DEPLOYMENT_NANO', value: foundryDeploymentNano }
          { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
          { name: 'COSMOS_DATABASE', value: 'matchhealth' }
          { name: 'COSMOS_CONTAINER', value: 'moments' }
          { name: 'WEBPUBSUB_ENDPOINT', value: 'https://${pubsub.properties.hostName}' }
          { name: 'WEBPUBSUB_HUB', value: 'overlays' }
          { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        ]
      } ]
    }
  }
}

// Hosts web/index.html. Free tier: $0, deployed separately by
// .github/workflows/swa-deploy.yml (this resource just needs to exist;
// content deploy needs the Static Web Apps GitHub Action + deployment token).
resource staticWebApp 'Microsoft.Web/staticSites@2024-04-01' = {
  name: '${prefix}-web'
  location: location
  sku: { name: 'Free', tier: 'Free' }
  properties: {}
}

// --- Role assignments: managed identity only, no API keys anywhere ---------

resource replayFoundryRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, replayJob.id, cognitiveServicesOpenAIUserRoleId)
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: replayJob.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource replayPubSubRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(pubsub.id, replayJob.id, webPubSubServiceOwnerRoleId)
  scope: pubsub
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', webPubSubServiceOwnerRoleId)
    principalId: replayJob.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource negotiatePubSubRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(pubsub.id, negotiateApp.id, webPubSubServiceOwnerRoleId)
  scope: pubsub
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', webPubSubServiceOwnerRoleId)
    principalId: negotiateApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource replayCosmosRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmos
  name: guid(cosmos.id, replayJob.id, cosmosDataContributorRoleId)
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    principalId: replayJob.identity.principalId
    scope: cosmos.id
  }
}

output negotiateUrl string = 'https://${negotiateApp.properties.configuration.ingress.fqdn}/negotiate'
output staticWebAppUrl string = 'https://${staticWebApp.properties.defaultHostname}'
output replayImageUsed string = replayImage
