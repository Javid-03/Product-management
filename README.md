# Product Importer - Acme Inc.

A scalable web application for importing and managing products from CSV files (supports up to 500,000 records). Built with FastAPI, Celery, PostgreSQL, and Redis for handling large datasets efficiently.

## Features

- **CSV Import**: Upload large CSV files (up to 500k products) with real-time progress tracking
- **Product Management**: View, create, update, and delete products through a web interface
- **Filtering & Pagination**: Filter by SKU, name, description, or active status with paginated results
- **Bulk Operations**: Delete all products with confirmation dialog
- **Webhook Management**: Configure and test webhooks via UI
- **Case-Insensitive SKU**: Automatic deduplication based on case-insensitive SKU matching

## Tech Stack

- **Framework**: FastAPI
- **Task Queue**: Celery with Redis broker
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Frontend**: HTML/CSS/JavaScript with HTMX for dynamic updates
- **Deployment**: Configured for Render.com

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL
- Redis

### Local Development

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd Product-management
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Set environment variables:
   ```bash
   export DATABASE_URL="postgresql://user:password@localhost:5432/productdb"
   export REDIS_URL="redis://localhost:6379/0"
   ```

4. Start PostgreSQL and Redis (using Docker Compose):
   ```bash
   docker-compose up -d
   ```

5. Run database migrations (tables are auto-created on startup):
   ```bash
   # Tables are created automatically via Base.metadata.create_all()
   ```

6. Start the FastAPI server:
   ```bash
   uvicorn app.main:app --reload
   ```

7. In a separate terminal, start the Celery worker:
   ```bash
   celery -A app.celery_app.celery worker --loglevel=info
   ```

8. Open http://localhost:8000 in your browser

## CSV Format

The CSV file should have the following columns:
- `sku` (required): Product SKU (case-insensitive, must be unique)
- `name` (optional): Product name
- `description` (optional): Product description

Example:
```csv
sku,name,description
ABC123,Product Name,Product description
XYZ789,Another Product,Another description
```

## Deployment

The project includes a `render.yaml` configuration file for easy deployment on Render.com:

1. Push your code to GitHub
2. Connect your repository to Render
3. Render will automatically detect `render.yaml` and provision:
   - Web service (FastAPI)
   - Worker service (Celery)
   - PostgreSQL database
   - Redis instance

Environment variables are automatically configured from service connections.

## Architecture

- **Web Service**: Handles HTTP requests, file uploads, and serves the UI
- **Worker Service**: Processes CSV imports asynchronously using Celery
- **Database**: Stores products and webhooks
- **Redis**: Used as Celery broker and for task progress tracking

The upload process is designed to handle long-running operations (e.g., Heroku's 30-second timeout) by offloading work to background Celery tasks.

## License

This project is created for Acme Inc. as part of a technical assessment.

