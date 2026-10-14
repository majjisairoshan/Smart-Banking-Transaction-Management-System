"""CTPB Bank — a Banking Transaction System built for the Computational
Thinking & Programming course.

Package layout
--------------
bank.config      – 12-factor configuration
bank.db          – thread-safe PostgreSQL connection pool (Singleton)
bank.models      – domain model: abstract Account hierarchy, DTOs
bank.repository  – data-access layer (Repository pattern over the pool)
bank.services    – business logic / use-cases (transfer, interest, reports)
bank.algorithms  – hand-rolled algorithms (merge sort, binary search, greedy,
                   sliding-window risk rules) with complexity notes
bank.security    – password hashing, session guards, login rate limiting
bank.utils       – formatting / masking helpers (pure functions)
bank.routes      – Flask blueprints: auth, user, admin, api
"""

__version__ = "1.0.0"
