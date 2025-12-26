# 🍿 Popcorn Sales Manager

A volunteer-run web application to help Scouts and families manage in-person popcorn sales for fundraising.

## Overview

Popcorn Sales Manager is an open-source, serverless application designed for Scouting America units to track popcorn sales during fall fundraising campaigns. Built with modern web technologies and AWS services, it provides families with an easy-to-use interface for managing orders, tracking inventory, and generating reports.

## Features

- **Seller Profile Management**: Create and manage multiple seller profiles (for families with multiple Scouts)
- **Campaign Tracking**: Organize sales by yearly campaigns with automatic metadata inheritance
- **Order Management**: Track customer orders with payment methods, delivery status, and line items
- **Catalog Support**: Use admin-managed catalogs or create custom product catalogs
- **Sharing & Collaboration**: Share profiles with trusted adults (READ or WRITE permissions)
- **Reports**: Generate CSV/XLSX reports for unit submission and personal tracking
- **Social Login**: Sign in with Google, Facebook, or Apple accounts
- **Privacy-First**: All data encrypted in-flight and at-rest, COPPA compliance warnings

## Tech Stack

### Frontend
- **React** + **TypeScript** + **Vite**
- **Material-UI (MUI)** for components
- **Apollo Client** for GraphQL
- **react-router** for navigation

### Backend
- **AWS AppSync** (GraphQL API)
- **AWS Lambda** (Python 3.13)
- **Amazon DynamoDB** (single-table design)
- **Amazon Cognito** (authentication with social providers)
- **Amazon S3** (static hosting + report exports)
- **Amazon CloudFront** (CDN)

### Infrastructure
- **AWS CDK** (Python) for infrastructure as code
- **uv** for Python package management
- **npm** for frontend tooling

## Project Status

**Current Phase**: Phase 0 - Infrastructure & Foundation (In Progress)

See [TODO.md](TODO.md) for detailed progress and roadmap.

## Getting Started

### Prerequisites

- **uv** (Python package manager)
- **AWS CLI** (configured with credentials)
- **Docker** (for optional LocalStack testing)
- **Node.js** v22+ and **npm** v10+

### Installation

(Coming soon - project is in early development)

## Development

### Python/Backend Development

```bash
# Install dependencies
uv sync

# Format code
uv run isort src/ tests/
uv run ruff format src/ tests/
# or: uv run ruff check src/ tests/ (to only check formatting) 

# Type check
uv run mypy src/

# Run tests with coverage
uv run pytest tests/unit --cov=src --cov-fail-under=100
```

### Frontend Development

```bash
# Install dependencies
npm install

# Start dev server
npm run dev

# Format and lint
npm run format
npm run lint

# Type check
npm run typecheck

# Run tests with coverage
npm run test -- --coverage
```

### CDK Deployment

```bash
# Synthesize CloudFormation template
cdk synth

# Preview changes
cdk diff

# Deploy to dev environment
cdk deploy --profile dev
```

## Architecture

See the `.temp/planning_documents/` directory for complete architecture documentation:

- [System Architecture & SRS](.temp/planning_documents/psm_srs_v1.md)
- [GraphQL Schema](.temp/planning_documents/graphql_schema_v1.md)
- [DynamoDB Physical Schema](.temp/planning_documents/dynamodb_physical_schema_v1.md)
- [Auth & Sharing Model](.temp/planning_documents/auth_and_sharing_model.md)
- [Tech Stack Overview](.temp/planning_documents/tech_stack_and_architecture.md)
- [Admin Console Spec](.temp/planning_documents/admin_console_spec_v1.md)

## Testing

This project maintains **100% unit test coverage** for both Python and TypeScript code.

### Backend Testing
- **Unit tests**: `moto` for AWS service mocking
- **Integration tests**: LocalStack Pro (if OSS license approved) or AWS dev account

### Frontend Testing
- **Unit/Component tests**: Vitest with React Testing Library
- **E2E tests** (optional): Playwright

## Contributing

This is a volunteer-run project. Contributions are welcome! Please read [AGENT.md](AGENT.md) for development guidelines.

### Contribution Guidelines

1. **Never push directly to main** - always use pull requests
2. **100% test coverage required** - all tests must pass
3. **Follow code quality standards** - isort, ruff, mypy (Python); ESLint, Prettier (TypeScript)
4. **Document your changes** - update README and relevant docs

## Code Quality

- **Python**: isort + black + mypy + pytest (100% coverage)
- **TypeScript**: ESLint + Prettier + Vitest (100% coverage)
- **Git workflow**: Feature branches + pull requests only

See [AGENT.md](AGENT.md) for detailed quality standards.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Volunteer Context

This project is volunteer-maintained and operated. Operating costs are paid by volunteers. If you find this project helpful, consider:

- Contributing code or documentation
- Reporting bugs and suggesting features
- Sponsoring the project (link TBD)

## Privacy & Compliance

- **COPPA Warning**: Only users 13+ may create accounts
- **Data Encryption**: All data encrypted in-flight (HTTPS) and at-rest (AWS-managed encryption)
- **Privacy Policy**: Users are responsible for their own customer data; customer-level privacy requests are handled directly by sellers

## Support

For questions or issues, please open a GitHub issue. Response times may vary due to volunteer availability.

## Acknowledgments

Built for the Scouting America community by volunteers who understand the challenges of managing popcorn sales. Special thanks to all contributors and families who provided feedback.

---

**Note**: This project is in active development. The initial release (v1) is targeted for fall 2025 popcorn sales campaign.
