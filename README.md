# SmartPresence Backend

REST API for **SmartPresence**, a school attendance platform. Student attendance is taken with AI face recognition, teachers check in and out with a photo, and parents follow their children's attendance and receive notifications.

Built with Django 5.2, Django REST Framework and PostgreSQL.

## Features

- **Roles**: Super Admin, School Admin, Teacher and Parent. Each role only sees data in its own scope.
- **Schools and academics**: academic years, classes, sections, class-sections, holidays and working-day calendars.
- **Teachers, students and parents**: CRUD, CSV/Excel bulk upload, class-section assignment, teacher transfers.
- **Student attendance**: face registration and verification through an external AI service, run as background jobs. Manual sessions, record edits, and lock/unlock are also supported.
- **Teacher attendance**: photo check-in/check-out, admin verification, per-school settings and summaries.
- **Notifications**: messages with attachments, a per-user inbox, and Web Push (VAPID).
- **Reports**: CSV/Excel exports.
- **System**: public health check (`GET /api/system/health/`), maintenance mode (503 for everyone except Super Admins), activity logs, rate limiting, request IDs.
- **Website**: public testimonials, partners and a contact form with an optional Cloudflare Turnstile check.

## Tech stack

| Concern | Tool |
|---|---|
| Framework | Django 5.2, Django REST Framework |
| Database | PostgreSQL (`psycopg` 3) |
| Auth | SimpleJWT, sent in HttpOnly cookies |
| Media | Local files in development, Cloudinary in production |
| Static files | WhiteNoise |
| Push | `pywebpush` |
| Server | Gunicorn |

## Project layout

```
config/               Settings, root URLs, WSGI/ASGI
common/               Shared responses, pagination, permissions, throttling, emails, CSV import
accounts/             Custom User model, cookie JWT auth, profiles, user management
schools/              Schools and school admins
academics/            Academic years, classes, sections, holidays, working days
teachers/             Teacher profiles and class-section assignment
students/             Student profiles and images
parents/              Parents and the parent portal
attendance_student/   AI face registration/verification and attendance sessions
attendance_teacher/   Teacher check-in/check-out
notifications/        Notifications, inbox, Web Push
reports/              CSV/Excel exports
