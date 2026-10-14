# 🏦 Smart Banking & Transaction Management System (CTPB Bank)

A full-stack banking web application built with **Python, Flask, PostgreSQL, HTML, CSS, and JavaScript**. CTPB Bank provides secure customer and administrator portals for account management, balance enquiry, money transfers, transaction history, and fraud detection.

The project demonstrates computational thinking, data structures, algorithms, database transactions, concurrency, software testing, and DevOps practices.

## 📌 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Technology Stack](#-technology-stack)
- [System Architecture](#-system-architecture)
- [Algorithms Used](#-algorithms-used)
- [Account Rules](#-account-rules)
- [Project Structure](#-project-structure)
- [Installation and Setup](#-installation-and-setup)
- [Running the Application](#-running-the-application)
- [Testing](#-testing)
- [Security Features](#-security-features)
- [Limitations](#-limitations)
- [Future Enhancements](#-future-enhancements)
- [Author](#-author)

## 📖 Overview

CTPB Bank is a browser-based banking application designed to manage financial transactions safely and maintain an auditable transaction ledger.

The application supports Savings and Current accounts, customer authentication, account validation, atomic money transfers, fraud detection, and administrative operations.

A layered architecture separates the presentation layer, Flask routes, business services, database repositories, and PostgreSQL storage.

## ✨ Features

### 👤 Customer Portal

- Secure customer login and session management.
- Live account balance enquiry.
- Savings and Current account support.
- Payee account validation before transferring money.
- Money transfers with duplicate-request protection.
- Transaction history with filtering and pagination.
- Transaction visualizations and balance summaries.
- ATM-style currency denomination breakdown.

### 🛡️ Administrator Portal

- Dedicated administrator login.
- Dashboard with banking and deposit statistics.
- Customer creation and account management.
- Freeze and unfreeze accounts.
- Suspicious transaction monitoring.
- Interest accrual for eligible Savings accounts.
- Complete transaction ledger inspection.

### 💳 Transaction Management

- Atomic database transactions.
- Idempotency keys to prevent duplicate transfers.
- Double-entry ledger recording.
- Row-level locking for concurrent transfers.
- Deterministic lock ordering to reduce deadlocks.
- Database constraints for transaction integrity.

### 🧪 Software Quality

- Unit testing with pytest.
- Property-based testing with Hypothesis.
- Integration and end-to-end tests.
- Static analysis with Ruff and MyPy.
- Docker-based deployment support.
- GitHub Actions continuous integration.

## 🛠️ Technology Stack

| Component | Technology |
|---|---|
| Programming language | Python 3.12+ |
| Backend framework | Flask |
| Frontend | HTML, CSS, JavaScript |
| Database | PostgreSQL |
| Database driver | psycopg2 |
| Connection pooling | ThreadedConnectionPool |
| Templates | Jinja2 |
| Unit testing | pytest |
| Property-based testing | Hypothesis |
| Linting | Ruff |
| Type checking | MyPy |
| Containerization | Docker and Docker Compose |
| CI/CD | GitHub Actions |

## 🏗️ System Architecture

The application follows a layered architecture.

```text
              Customer / Admin
                     |
                     v
             Browser Interface
          HTML + CSS + JavaScript
                     |
                     v
              Flask Routes
       Authentication / User / Admin / API
                     |
                     v
               Service Layer
       Transfer / Balance / Interest
                     |
                     v
             Repository Layer
         SQL Queries and Row Locks
                     |
                     v
              PostgreSQL
          Users / Accounts / Transactions
```

### Main Modules

- `app.py` — Flask application entry point.
- `bank/models.py` — Account abstraction and account types.
- `bank/services.py` — Banking operations and transfer planning.
- `bank/repository.py` — Database queries and transaction persistence.
- `bank/algorithms.py` — Sorting, searching, denomination, and top-K algorithms.
- `bank/db.py` — Database connection pool.
- `bank/security.py` — Password hashing and rate limiting.
- `templates/` — HTML templates.
- `static/` — CSS, JavaScript, and frontend assets.
- `tests/` — Automated tests.
- `db/schema.sql` — Database schema.
- `scripts/seed.py` — Database creation and seed data.
- `.github/workflows/ci.yml` — Continuous integration configuration.

## 🧠 Algorithms Used

| Algorithm / Technique | Purpose | Complexity |
|---|---|---|
| Merge Sort | Sort transaction records | O(n log n) |
| Binary Search | Search sorted transaction data | O(log n) |
| Greedy Algorithm | Calculate currency denomination breakdown | O(d) |
| Sliding Window | Detect rapid transactions and limit login attempts | O(k) per examined window |
| Top-K Selection | Identify large transactions for the admin dashboard | O(n log n), as described in the project report |
| Double-Entry Ledger | Maintain auditable records of money transfers | Depends on database operations |
| Row-Level Locking | Protect concurrent account updates | Depends on database contention |
| Idempotency | Prevent duplicate processing of repeated requests | Supported by a unique database constraint |

Here, `n` represents the number of records, `d` the number of currency denominations, and `k` the number of records examined in a sliding window.

## 💰 Account Rules

### Savings Account

- Minimum permitted balance: ₹1,000.
- Annual interest rate: 4%.
- Debits that violate the minimum balance are rejected.

### Current Account

- Permitted overdraft: up to ₹50,000.
- Minimum permitted balance: −₹50,000.
- No default interest accrual.

### Transaction Integrity

Transfers are validated before execution and then processed within a database transaction. Account rows are locked in a consistent order, balance changes and ledger recording are committed together, and failures roll back the transaction.

Unique transaction references and idempotency keys help prevent duplicate ledger entries.

## 📂 Project Structure

```text
CTPB-Bank/
├── app.py
├── requirements.txt
├── docker-compose.yml
├── Dockerfile
├── bank/
│   ├── models.py
│   ├── services.py
│   ├── repository.py
│   ├── algorithms.py
│   ├── db.py
│   └── security.py
├── db/
│   └── schema.sql
├── scripts/
│   └── seed.py
├── templates/
├── static/
├── tests/
└── .github/
    └── workflows/
        └── ci.yml
```

*The structure above illustrates the main components described in the project report. Confirm the actual filenames in your repository before publishing this tree.*

## ⚙️ Installation and Setup

### Prerequisites

Install the following software:

- Python 3.12 or newer.
- PostgreSQL.
- Git.
- pip.

Docker and Docker Compose can also be used if the required configuration files are present.

### Step 1: Clone the Repository

Replace the placeholder with your actual GitHub repository URL.

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
```

Navigate to the project directory:

```bash
cd YOUR_REPOSITORY
```

### Step 2: Create a Virtual Environment

**Windows:**

```bash
python -m venv venv
venv\Scripts\activate
```

**Linux / macOS:**

```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install Dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Configure PostgreSQL

Make sure the PostgreSQL server is running.

The application uses a PostgreSQL database named `CTPBD`. Configure the database connection settings according to the configuration supported by your project.

If the database and required tables are not already created, use the project's initialization script in the next step.

### Step 5: Create and Seed the Database

Run the following command from the project root:

```bash
python -m scripts.seed --create-db --seed
```

This command creates the database and populates it with seed data, according to the supplied project setup.

### Step 6: Start the Application

```bash
python app.py
```

Open the local URL displayed in your terminal.

**Important:** If your repository contains a Docker Compose configuration, you can alternatively start the configured services with:

```bash
docker compose up --build
```

## 🧪 Testing

Run the automated test suite:

```bash
pytest -q
```

Run Ruff:

```bash
ruff check .
```

Run MyPy:

```bash
mypy .
```

The project report records the following results:

- 72 automated tests.
- Approximately 85% line coverage.
- Zero Ruff issues.
- Zero MyPy issues.

These figures are reported project results; rerun the checks against your current repository to verify them.

## 🔐 Security Features

- Scrypt password hashing.
- Login rate limiting.
- Role-based route protection.
- Signed Flask sessions.
- Atomic PostgreSQL transactions.
- Row-level locking and deterministic lock ordering.
- Unique idempotency keys.
- Database constraints and an auditable ledger.
- Suspicious transaction flagging.

**Security notice:** This is an academic demonstration project, not a certified production banking platform. Before public deployment, configure a strong secret key, enable HTTPS, implement CSRF protection and multifactor authentication, review database permissions, and apply appropriate operational security controls.

Do not commit passwords, API keys, production credentials, or sensitive database configuration to GitHub.

## ⚠️ Limitations

- Payee validation requires an exact account number.
- Multi-currency transactions are not supported.
- Scheduled standing orders are not supported.
- CSRF protection and multifactor authentication require further implementation.
- Horizontal scaling beyond a single PostgreSQL instance is not established.
- Production-grade deployment hardening remains future work.

## 🚀 Future Enhancements

- Add multifactor authentication and stronger session security.
- Introduce machine-learning-based fraud detection.
- Integrate UPI and external payment gateways.
- Add transaction reversal workflows with administrator approval.
- Implement asynchronous statement generation and notifications.
- Expand automated testing and performance benchmarks.
- Improve scalability through read replicas and connection-pool tuning.

## 👨‍💻 Author

**M. Sai Roshan**

M.Tech — Artificial Intelligence and Data Science  
Koneru Lakshmaiah University (KL University)

- GitHub: [@majjisairoshan](https://github.com/majjisairoshan)
- LinkedIn: [Majji Sai Roshan](https://www.linkedin.com/in/majji-sai-roshan-237947261/)
- Portfolio: [Personal Portfolio](https://majjisairoshan.netlify.app/)

## 🎓 Academic Project

**Project:** Smart Banking & Transaction Management System (CTPB Bank)  
**Course:** 26CS5101E — Computational Thinking and Programming  
**Academic Year:** 2026–2027  
**Institution:** K L University

---

⭐ If you find this project useful for learning Python, Flask, PostgreSQL, algorithms, and secure transaction processing, consider starring the repository.

*Developed for academic learning and demonstration purposes.*
