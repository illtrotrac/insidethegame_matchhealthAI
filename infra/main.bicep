// Match Health AI — cost-lean Azure footprint (scale to zero, free tiers).
// Skeleton: fill in images, role assignments and model deployments before deploying.
targetScope = 'resourceGroup'

param location string = resourceGroup().location
param prefix string = 'matchhealth'

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

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: '${prefix}-cosmos'
  location: location
  properties: {
    databaseAccountOfferType: 'Standard'
    enableFreeTier: true // one free-tier account per subscription
    locations: [ { locationName: location } ]
    disableLocalAuth: true
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

// Replay + crew run as an on-demand job: billed only while a match replays.
resource replayJob 'Microsoft.App/jobs@2024-03-01' = {
  name: '${prefix}-replay'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    environmentId: env.id
    configuration: { triggerType: 'Manual', replicaTimeout: 7200, manualTriggerConfig: { parallelism: 1 } }
    template: {
      containers: [ {
        name: 'replay'
        image: 'mcr.microsoft.com/k8se/quickstart:latest' // TODO: replace with ACR image
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'MATCHHEALTH_MOCK_LLM', value: '0' }
          { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
          { name: 'WEBPUBSUB_ENDPOINT', value: 'https://${pubsub.properties.hostName}' }
          { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        ]
      } ]
    }
  }
}

// TODO: Microsoft Foundry project + mini/nano model deployments, Static Web App,
// and role assignments for the job's managed identity (Cosmos, Web PubSub, Foundry).
