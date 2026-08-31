# Admin Dashboard Architecture

```text
frontend/src/
├── api/adminDashboard.ts
├── types/admin.ts
├── components/admin/
│   ├── AdminMetricCard.tsx
│   ├── ApiTester.tsx
│   ├── SwaggerConsoleModal.tsx
│   └── TraceTimeline.tsx
└── routes/admin/
    ├── SalesManagementPage.tsx
    ├── ObservabilityPage.tsx
    └── ConflictsTab.tsx

backend/
├── routers/
│   ├── admin_sales.py
│   ├── admin_observability.py
│   └── admin_conflicts.py
└── schemas/
    ├── admin_dashboard.py
    └── conflict_flag.py
```

The Admin UI consumes live application data. Missing sources are explicit null/empty
states: deal conversion requires a future CRM contract model, similarity requires the
ingestion pipeline to persist a score, and token cost requires deployment-specific rates.

Main endpoints:

- `GET /api/v1/admin/sales`
- `PATCH /api/v1/admin/sales/{sale_id}/active`
- `POST /api/v1/admin/sales/reassign`
- `GET /api/v1/admin/observability`
- `GET /api/v1/admin/observability/traces/{run_id}`
- `GET /api/v1/admin/conflicts`
- FastAPI-native `/docs` and `/redoc`
