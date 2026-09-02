# GateFlow

GateFlow is an API gateway and traffic-management platform for controlling, observing, and protecting access to upstream services.

The project is organized as a Go backend and a React frontend:

- **Gateway backend**: API-key authentication, request proxying, rate limiting, analytics, in-memory repositories, and HTTP APIs.
- **Operations dashboard**: a React/Vite interface for viewing gateway analytics, managing clients, and configuring routes.
- **Mock upstream**: a local service intended for development and end-to-end testing.

> **Repository status:** this checkout currently contains the project directory layout, the frontend dependency lockfile, and a built frontend bundle. The application source files and build manifests (`go.mod`, `package.json`, and related configuration) must be restored before the development commands below can be run.

## Features

- API-key based client authentication
- Configurable upstream routes
- Reverse proxying to upstream services
- Request rate limiting
- Request analytics and logs
- Client management
- In-memory persistence for local development
- Mock upstream service for testing gateway flows
- Web dashboard for gateway operations

## Architecture

```text
                          +-------------------+
                          |   React dashboard |
                          |    Vite frontend  |
                          +---------+---------+
                                    |
                                    | HTTP API
                                    v
+-------------+        +------------+-------------+        +----------------+
| API clients | -----> |       GateFlow gateway   | -----> | Upstream APIs  |
+-------------+        | auth | routes | proxy    |        +----------------+
                       | rate limit | analytics   |
                       +------------+-------------+
                                    |
                                    v
                         +-------------------------+
                         | In-memory repositories  |
                         +-------------------------+

                         +-------------------------+
                         | Mock upstream service   |
                         | local development only  |
                         +-------------------------+
```

## Repository Layout

```text
.
├── backend/
│   ├── cmd/
│   │   ├── gateway/       # Gateway application entry point
│   │   └── mockupstream/  # Local upstream test service
│   └── internal/
│       ├── analytics/     # Request metrics and logs
│       ├── apikey/        # API-key validation
│       ├── app/           # Application wiring
│       ├── config/        # Runtime configuration
│       ├── domain/        # Core models and contracts
│       ├── httpapi/       # HTTP handlers and routes
│       ├── middleware/    # Cross-cutting HTTP middleware
│       ├── proxy/         # Upstream request forwarding
│       ├── ratelimit/     # Traffic limiting
│       └── repository/    # Persistence abstractions
│           └── memory/    # In-memory implementations
├── frontend/
│   └── src/               # React dashboard source
├── scripts/               # Development and automation scripts
└── .github/               # GitHub workflows and configuration
```

## Requirements

- Go 1.22 or later
- Node.js 20 or later
- npm 10 or later

The frontend uses React, React Router, TanStack Query, Recharts, Lucide React, TypeScript, Vite, Tailwind CSS, and Vitest.

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/ShaliniBangamuwage/GateFlow.git
cd GateFlow
```

### 2. Restore the application source

Before starting the services, ensure the repository contains:

- `backend/go.mod`
- Go source files under `backend/cmd` and `backend/internal`
- `frontend/package.json`
- Frontend source files under `frontend/src`

These files are not present in the current checkout, so the commands below are the expected project workflow rather than executable commands for this snapshot.

### 3. Start the gateway backend

```bash
cd backend
go mod download
go run ./cmd/gateway
```

### 4. Start the mock upstream in a second terminal

```bash
cd backend
go run ./cmd/mockupstream
```

### 5. Start the frontend in a third terminal

```bash
cd frontend
npm ci
npm run dev
```

Open the local URL printed by Vite, normally `http://localhost:5173`.

## Configuration

Configuration is read from environment variables in the backend configuration package. Use an untracked `.env` file for local values and never commit secrets.

The expected local configuration should define, as applicable:

| Setting | Purpose | Example |
| --- | --- | --- |
| `PORT` | Gateway listen port | `8080` |
| `UPSTREAM_URL` | Default upstream service URL | `http://localhost:8081` |
| `API_KEY` | Development API key | `local-development-key` |
| `VITE_API_URL` | Frontend API base URL | `http://localhost:8080` |

The exact variable names and defaults should be confirmed against the restored backend configuration and frontend API client before deployment.

## API Surface

The dashboard is designed to communicate with the gateway through these resource areas:

| Area | Purpose |
| --- | --- |
| `/api/analytics/summary` | Aggregated gateway metrics |
| `/api/analytics/logs` | Recent request and proxy logs |
| `/api/clients` | Client and API-key management |
| `/api/routes` | Upstream route management |

The final request methods, payload schemas, authentication headers, and response codes are defined by the restored HTTP handlers and should be treated as the source of truth.

## Frontend Development

Typical frontend commands after restoring `frontend/package.json` are:

```bash
npm ci
npm run dev       # Start the Vite development server
npm run build     # Create a production build
npm run preview   # Preview the production build locally
npm run test      # Run Vitest tests
npm run lint      # Run ESLint
```

## Backend Development

From `backend/`:

```bash
go test ./...
go vet ./...
go run ./cmd/gateway
go run ./cmd/mockupstream
```

## Testing the Gateway Locally

1. Start the mock upstream service.
2. Start the GateFlow gateway.
3. Create or configure an API client and route.
4. Send a request through the gateway using the configured API key.
5. Confirm the upstream response is returned.
6. Check the dashboard analytics and request logs.
7. Send requests above the configured limit and verify rate limiting is applied.

Example request shape:

```bash
curl http://localhost:8080/<gateway-route> -H "X-API-Key: <your-api-key>"
```

Replace `<gateway-route>` and `<your-api-key>` with values from the running application.

## Production Considerations

- Store API keys and upstream credentials in a secrets manager.
- Use HTTPS between clients, GateFlow, and upstream services.
- Replace in-memory repositories with durable storage before production use.
- Configure rate limits per client and route.
- Restrict administrative endpoints behind authentication and network controls.
- Set structured logging and monitoring for gateway errors, latency, and rejected requests.
- Build and serve the frontend from a controlled deployment pipeline.

## Contributing

1. Create a focused branch from `main`.
2. Make the smallest change that addresses the issue.
3. Add or update tests for behavior changes.
4. Run the backend and frontend checks locally.
5. Open a pull request with a clear description and validation notes.

## License

No license file is currently included. Add a license before distributing GateFlow publicly.

## Maintainer

[Shalini Bangamuwage](https://github.com/ShaliniBangamuwage)
