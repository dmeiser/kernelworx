# 🍿 KernelWorx

A volunteer-run web application to help Scouts and families manage in-person popcorn sales for fundraising.

## Overview

KernelWorx is an open-source, serverless application designed for Scouting America units to track popcorn sales during fall fundraising campaigns. Built with modern web technologies and AWS services, it provides families with an easy-to-use interface for managing orders, tracking inventory, and generating reports.

## Features

- **Seller Profile Management**: Create and manage multiple seller profiles (for families with multiple Scouts)
- **Campaign Tracking**: Organize sales by yearly campaigns with automatic metadata inheritance
- **Order Management**: Track customer orders with payment methods, delivery status, and line items
- **Catalog Support**: Use admin-managed catalogs or create custom product catalogs
- **Sharing & Collaboration**: Share profiles with trusted adults (READ or WRITE permissions)
- **Reports**: Generate CSV/XLSX reports for unit submission and personal tracking
- **Social Login**: Sign in with Google or Facebook accounts
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
- **OpenTofu** for infrastructure as code
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

### OpenTofu Deployment

```bash
# Initialize (first time only)
cd tofu/environments/dev
tofu init

# Preview changes
tofu plan

# Deploy to dev environment
tofu apply
```

## Architecture

For detailed architecture and requirements documentation, see:
- [AGENT.md](AGENT.md) - Development guidelines and domain model reference
- [docs/](docs/) - Developer guides and getting started instructions

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

### Docker Tags

The project publishes official Docker images with a standardized tagging policy:

- `:latest`: Always points to the most recent tip of the `main` branch, rebuilt nightly.
- `:<major>`: Points to the latest release of a major version (e.g., `:1`), updated with each release and rebuilt nightly for security patches.
- `:<major>.<minor>`: Points to the latest release of a minor version (e.g., `:1.2`), updated with each release and rebuilt nightly.
- `:<major>.<minor>.<patch>`: Immutable tags for specific releases (e.g., `:1.2.3`). Use these for production stability.

Images are rebuilt nightly to include the latest OS security updates while preserving application version stability for floating tags.

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
