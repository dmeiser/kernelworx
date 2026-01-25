# Data Schema - Popcorn Sales Manager

Visual schema documentation for the data model using entity-relationship diagrams.

## Database Architecture

```mermaid
erDiagram
    ACCOUNT ||--o{ SELLER_PROFILE : owns
    ACCOUNT ||--o{ CATALOG : creates
    ACCOUNT ||--o{ SHARE : receives
    ACCOUNT ||--o{ INVITE : receives
    ACCOUNT ||--o{ SHARED_CAMPAIGN : creates
    
    SELLER_PROFILE ||--o{ CAMPAIGN : contains
    SELLER_PROFILE ||--o{ SHARE : "shared via"
    SELLER_PROFILE ||--o{ INVITE : "invited via"
    
    CAMPAIGN ||--o{ ORDER : contains
    CAMPAIGN ||--o{ CATALOG : uses
    CAMPAIGN }o--|| SHARED_CAMPAIGN : "created from"
    
    ORDER }o--|| CAMPAIGN : "placed in"
    ORDER }o--|| SELLER_PROFILE : "for profile"
    
    CATALOG ||--o{ CAMPAIGN : "used by"
    CATALOG }o--|| ACCOUNT : "owned by"
    
    SHARE }o--|| SELLER_PROFILE : grants
    SHARE }o--|| ACCOUNT : "to account"
    
    INVITE }o--|| SELLER_PROFILE : "for profile"
    INVITE }o--|| ACCOUNT : "sent to"
    
    SHARED_CAMPAIGN }o--|| CATALOG : uses
    SHARED_CAMPAIGN ||--o{ CAMPAIGN : "template for"
```

## Table Structures

### ACCOUNT
```mermaid
classDiagram
    class ACCOUNT {
        accountId: String (PK)
        email: String (GSI)
        givenName: String
        familyName: String
        city: String
        state: String
        unitType: String
        unitNumber: Integer
        isAdmin: Boolean
        preferences: JSON
        createdAt: DateTime
        updatedAt: DateTime
    }
```

### SELLER_PROFILE
```mermaid
classDiagram
    class SELLER_PROFILE {
        ownerAccountId: String (PK)
        profileId: String (SK, GSI)
        sellerName: String
        createdAt: DateTime
        updatedAt: DateTime
    }
```

### CAMPAIGN
```mermaid
classDiagram
    class CAMPAIGN {
        profileId: String (PK)
        campaignId: String (SK, GSI)
        campaignName: String
        campaignYear: Integer
        startDate: DateTime
        endDate: DateTime
        catalogId: String (GSI)
        unitType: String
        unitNumber: Integer
        city: String
        state: String
        sharedCampaignCode: String
        isActive: Boolean
        totalOrders: Integer
        totalRevenue: Float
        unitCampaignKey: String (GSI)
        createdAt: DateTime (GSI)
        updatedAt: DateTime
    }
```

### ORDER
```mermaid
classDiagram
    class ORDER {
        campaignId: String (PK)
        orderId: String (SK, GSI)
        profileId: String (GSI)
        customerName: String
        customerEmail: String
        customerPhone: String
        items: JSON
        totalAmount: Float
        paymentMethod: String
        deliveryStatus: String
        notes: String
        createdAt: DateTime (GSI)
        updatedAt: DateTime
    }
```

### CATALOG
```mermaid
classDiagram
    class CATALOG {
        catalogId: String (PK)
        catalogName: String
        products: JSON
        ownerAccountId: String (GSI)
        catalogType: String
        isPublic: Boolean (GSI)
        isPublicStr: String
        isDeleted: Boolean
        createdAt: DateTime (GSI)
        updatedAt: DateTime
    }
```

### SHARE
```mermaid
classDiagram
    class SHARE {
        profileId: String (PK)
        targetAccountId: String (SK, GSI)
        permissions: StringSet
        createdAt: DateTime
        updatedAt: DateTime
    }
```

### INVITE
```mermaid
classDiagram
    class INVITE {
        inviteCode: String (PK)
        profileId: String (GSI)
        permissions: StringSet
        expiresAt: DateTime (TTL)
        createdAt: DateTime
    }
```

### SHARED_CAMPAIGN
```mermaid
classDiagram
    class SHARED_CAMPAIGN {
        sharedCampaignCode: String (PK)
        campaignName: String
        catalogId: String
        unitType: String
        unitNumber: Integer
        city: String
        state: String
        campaignYear: Integer
        createdBy: String (GSI)
        createdAt: DateTime (GSI)
        isActive: Boolean
        description: String
        unitCampaignKey: String (GSI)
    }
```

## Query Flows

### Get User's Profiles
```mermaid
flowchart TD
    A["User Calls getMyProfiles"] -->|Uses accountId| B["Query ACCOUNT→SELLER_PROFILE"]
    B -->|ownerAccountId = accountId| C["Return all profiles"]
```

### Get Campaign with Orders
```mermaid
flowchart TD
    A["User Requests Campaign"] -->|campaignId| B["Query CAMPAIGN by campaignId-index"]
    B -->|Returns Campaign| C["Query CAMPAIGN→CATALOG"]
    C -->|Returns Catalog| D["Query ORDER by campaignId"]
    D -->|Returns Orders| E["Merge Campaign + Catalog + Orders"]
```

### Check Profile Access
```mermaid
flowchart TD
    A["User Accesses Profile"] -->|profileId + accountId| B{Is Owner?}
    B -->|Yes: ownerAccountId = accountId| C["Full Access"]
    B -->|No| D["Query SHARE table"]
    D -->|Found entry| E["Check Permissions"]
    E -->|READ/WRITE| F["Grant Access"]
    D -->|Not Found| G["Deny Access"]
```

### Find Unit's Campaign
```mermaid
flowchart TD
    A["Search Unit Campaign"] -->|unitType + unitNumber + city + state + year| B["Build unitCampaignKey"]
    B -->|unitCampaignKey = Troop#123#Denver#CO#2025| C["Query CAMPAIGN unitCampaignKey-index"]
    C -->|Returns Campaign| D["Found!"]
```

## Data Flow: Create Campaign from Shared Template

```mermaid
sequenceDiagram
    User->>Frontend: Create campaign from shared code
    Frontend->>GraphQL: CreateCampaignFromShared(sharedCampaignCode)
    GraphQL->>Lambda: Validate code & permissions
    Lambda->>SHARED_CAMPAIGN: Get template (PK: sharedCampaignCode)
    Lambda->>CATALOG: Verify catalog exists
    Lambda->>CAMPAIGN: Create new campaign
    Lambda->>CAMPAIGN: Set sharedCampaignCode reference
    Lambda->>Frontend: Return new campaignId
    Frontend->>User: Redirect to campaign
```

## Data Flow: Share Profile with Invite Code

```mermaid
sequenceDiagram
    Owner->>Frontend: Generate invite for profile
    Frontend->>GraphQL: CreateInvite(profileId, permissions)
    GraphQL->>Lambda: Generate 8-char code
    Lambda->>INVITE: Put invite (PK: inviteCode)
    Lambda->>INVITE: Set expiresAt = now + 14 days
    Lambda->>Frontend: Return invite code & URL
    Frontend->>Owner: Display shareable link
    
    Recipient->>Frontend: Accept invite with code
    Frontend->>GraphQL: AcceptInvite(inviteCode)
    GraphQL->>Lambda: Look up invite
    Lambda->>INVITE: Query by inviteCode (PK)
    Lambda->>SHARE: Create share entry
    Lambda->>INVITE: Delete invite (now consumed)
    Lambda->>Frontend: Success
    Frontend->>Recipient: Profile now accessible
```

## Denormalization & Caching

```mermaid
flowchart TD
    A["Order Created/Updated"] -->|Triggers| B["Update CAMPAIGN"]
    B -->|Recalculate totalOrders| C["Count all orders for campaign"]
    C -->|Recalculate totalRevenue| D["Sum all order totalAmount"]
    D -->|Update CAMPAIGN| E["totalOrders, totalRevenue"]
    E -->|Enables fast| F["Dashboard queries without ORDER scans"]
```

## Index Strategy

```mermaid
graph TD
    subgraph "DynamoDB Tables"
        A["ACCOUNT<br/>PK: accountId"]
        B["SELLER_PROFILE<br/>PK: ownerAccountId + profileId"]
        C["CAMPAIGN<br/>PK: profileId + campaignId"]
        D["ORDER<br/>PK: campaignId + orderId"]
        E["CATALOG<br/>PK: catalogId"]
        F["SHARE<br/>PK: profileId + targetAccountId"]
        G["INVITE<br/>PK: inviteCode"]
        H["SHARED_CAMPAIGN<br/>PK: sharedCampaignCode"]
    end
    
    subgraph "Global Secondary Indexes"
        A1["ACCOUNT<br/>GSI: email"]
        B1["SELLER_PROFILE<br/>GSI: profileId"]
        C1["CAMPAIGN<br/>GSI1: campaignId<br/>GSI2: catalogId<br/>GSI3: unitCampaignKey<br/>GSI4: profileId+createdAt"]
        D1["ORDER<br/>GSI1: orderId<br/>GSI2: profileId+createdAt"]
        E1["CATALOG<br/>GSI1: ownerAccountId<br/>GSI2: isPublic+createdAt"]
        F1["SHARE<br/>GSI: targetAccountId"]
        G1["INVITE<br/>GSI: profileId"]
        H1["SHARED_CAMPAIGN<br/>GSI1: createdBy+createdAt<br/>GSI2: unitCampaignKey"]
    end
    
    A --> A1
    B --> B1
    C --> C1
    D --> D1
    E --> E1
    F --> F1
    G --> G1
    H --> H1
```

## Permission Model

```mermaid
graph TD
    A["User wants to access Profile"] -->|Check: ownerAccountId = user| B{Is Owner?}
    B -->|Yes| C["✓ Full Access<br/>Read + Write + Delete"]
    B -->|No| D["Query SHARE table"]
    D -->|Share exists| E{Has WRITE?}
    D -->|Share not found| F["✗ No Access"]
    E -->|Yes| G["✓ Write Access<br/>Read + Write"]
    E -->|No| H["✓ Read-Only Access<br/>Read Only"]
```

## State Management

### Active vs Inactive Campaigns
```mermaid
stateDiagram-v2
    [*] --> Active
    Active --> Inactive: endDate passed or set isActive=false
    Inactive --> Active: set isActive=true
    Active --> Archived: user explicitly archives
    
    note right of Active
        Appears in user's active campaigns list
        Orders can be created
        Shown in dashboards
    end note
    
    note right of Inactive
        Hidden from active list
        Orders cannot be created
        Historical data preserved
    end note
```

## Lifecycle: Order to Revenue

```mermaid
graph LR
    A["Customer places Order<br/>totalAmount = value"] -->|Triggers| B["Update CAMPAIGN<br/>totalOrders++<br/>totalRevenue += amount"]
    B -->|Denormalized data| C["Dashboard loads instantly<br/>No ORDER table scans"]
    A -->|Order contains| D["Line items array"]
    D -->|Product<br/>quantity"] E["Inventory tracking<br/>for reporting"]
```

## TTL: Invite Expiration

```mermaid
flowchart TD
    A["Invite created"] -->|expiresAt = now + 14 days| B["TTL enabled"]
    B -->|After 14 days| C["DynamoDB auto-deletes"]
    C -->|No manual cleanup needed| D["Cost efficient"]
    
    E["Invite accepted"] -->|Before expiration| F["User accepts invite<br/>Create SHARE entry"]
    F -->|Delete INVITE manually| G["Consumed, no TTL wait"]
```

## References

- **GraphQL Schema**: [tofu/schema/schema.graphql](../tofu/schema/schema.graphql)
- **DynamoDB Infrastructure**: [tofu/modules/dynamodb/main.tf](../tofu/modules/dynamodb/main.tf)
- **Authorization Rules**: [AGENT.md](AGENT.md#authorization-pattern)
- **Developer Guide**: [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)
