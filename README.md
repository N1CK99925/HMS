# HMS SaaS API

## 🏢 Overview
A multi-tenant **Hospital Management System (HMS)** built with FastAPI. This API handles medical records, billing, and staff management across multiple hospitals (tenants) using a hybrid database approach designed for scalability and HIPAA compliance.

## 🚀 Tech Stack
- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Python 3.11)
- **Databases**:
  - **PostgreSQL**: Relational data, billing, and structured transactions (via SQLAlchemy & Alembic).
  - **MongoDB**: Flexible schema for patients, staff, and tenant metadata (via Motor).
  - **Redis**: Caching, RBAC permission storage, and session management.
- **Security**: JWT-based authentication with custom multi-tenant & RBAC middleware.
- **Infrastructure**: Docker & Docker Compose.

## 🏗️ Architectural Highlights
- **Strict Multi-tenancy**: Automatically enforced via `TenantMiddleware`. The `tenant_id` is extracted from the JWT and used to scope every database query.
- **Hybrid Persistence**: Optimized storage strategy:
  - **SQL** for structured, transactional data (Billing).
  - **NoSQL** for flexible, nested medical records (Patients, Staff).
- **Comprehensive Audit Logging**: Every PHI (Protected Health Information) access or modification is recorded in a tamper-evident audit log.
- **Soft Deletes**: To maintain HIPAA compliance, records (like Patients) are never hard-deleted; they are marked with `deleted_at`.
- **JWT Rotation**: Secure authentication flow with short-lived access tokens and longer-lived refresh tokens stored in Redis.

## 📂 Project Structure
- `app/main.py`: Entry point and lifespan management (DB connections).
- `app/core/`: Configuration, database connectors, and security logic.
- `app/models/`: Hybrid data models (Postgres SQLAlchemy & Mongo Pydantic).
- `app/routers/`: Domain-specific API endpoints (Auth, Patients, Health).
- `app/middleware/`: Custom logic for Tenant isolation and RBAC.
- `app/scripts/`: Utility scripts for tenant provisioning.
- `app/migrations/`: Database migration scripts for both Postgres and MongoDB.

## 🔌 Primary API Endpoints

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Service health status (MongoDB, Redis, API) | No |
| `POST` | `/api/v1/auth/login` | Staff login & JWT issuance | No |
| `POST` | `/api/v1/auth/refresh` | Rotate access/refresh tokens | Yes (Refresh) |
| `POST` | `/api/v1/auth/logout` | Invalidate refresh token in Redis | Yes |
| `GET` | `/api/v1/patients` | List patients (Current Tenant only) | Yes |
| `POST` | `/api/v1/patients` | Register a new patient | Yes |
| `GET` | `/api/v1/patients/{id}` | Fetch specific patient record | Yes |
| `PATCH` | `/api/v1/patients/{id}` | Update patient demographics | Yes |
| `DELETE` | `/api/v1/patients/{id}` | Soft-delete patient record | Yes |

## 🚦 Getting Started

### 1. Environment Setup
Copy the example environment file and configure your local credentials:
```bash
cp .example.env .env
```

### 2. Running with Docker
The easiest way to get started is using Docker Compose:
```bash
docker-compose up --build
```
The API will be available at `http://localhost:8000`.

### 3. API Documentation
Access the interactive documentation (enabled in `DEBUG` mode):
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

## 🛠 Local Development
1. **Prepare Virtual Environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```
2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Provision Database**:
   ```bash
   python -m app.migrations.mongo_indexes  # Setup MongoDB indexes
   # Run Alembic migrations for Postgres (ensure POSTGRES_URL is set)
   alembic upgrade head
   ```
4. **Start Application**:
   ```bash
   uvicorn app.main:app --reload
   ```

## 🗺️ Roadmap
- [ ] **Billing Management**: Relational billing and invoicing using PostgreSQL.
- [ ] **Staff Management**: Role-based access and profile management for doctors and nurses.
- [ ] **Department Configuration**: Multi-tenant aware department and ward management.
- [ ] **Inventory & Pharmacy**: Tracking medical supplies and prescriptions (Planned).

## 📄 License
This project is licensed under the Apache License 2.0. See the [LICENSE](LICENSE) file for details.
