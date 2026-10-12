# SmartPresence API Reference

Base URL: `/api/`. Roles: **SA** = SUPER_ADMIN, **SCH** = SCHOOL_ADMIN, **T** = TEACHER, **P** = PARENT.

---

## 1. Global conventions

### Authentication
- JWT is read **only from the `access_token` HttpOnly cookie**; the `Authorization` header is ignored.
- Login sets `access_token` (1 day) and `refresh_token` (7 days, rotated + blacklisted on refresh). Cookies: HttpOnly, SameSite=Lax, path `/`, Secure when `DEBUG=False`.
- Frontend must send requests with credentials (`credentials: "include"` / `withCredentials: true`).

### Response envelope
```json
// success
{ "success": true,  "message": "...", "data": { } }
// error
{ "success": false, "message": "...", "errors": { } }
// paginated list (data)
{ "count": 42, "next": "url|null", "previous": "url|null", "results": [ ] }
```
- Lists accept `?page=` and `?page_size=` (default 20, max 100). Paginated lists usually return message `"Fetched successfully."`.
- Many lists also accept `?search=` and `?ordering=field` / `-field`.

### Common errors (every protected endpoint)
| Status | message | When |
|---|---|---|
| 401 | `Authentication required.` | Access cookie missing, invalid or expired |
| 403 | `Permission denied.` | Wrong role for the route |
| 404 | `<Thing> not found.` | Missing **or outside your scope** (scoping hides other schools' data as 404) |
| 400 | `Request failed.` / `Validation failed.` | Field errors; `errors` = `{field: [msgs]}` |
| 409 | specific message | Conflict (locked attendance, record referenced by others, duplicates) |
| 503 | `AI service is currently unavailable.` | Face-recognition service down |

### Scoping rules
- **SA**: everything.
- **SCH**: only their `managed_school`. Without a school, writes fail with 400 `"The authenticated user is not assigned as an administrator of any school."`.
- **T**: only their own assigned class-section (students, attendance, parents). Unassigned teachers get 400 `"You are not assigned to a class section, so you cannot manage students yet."`.
- **P**: only their own children and inbox.

---

## 2. Role-wise endpoint list

### SUPER_ADMIN
| Area | Endpoints |
|---|---|
| Auth/Profile | `POST auth/login/`, `POST auth/logout/`, `POST auth/refresh/`, `GET/PATCH auth/profile/`, `PATCH auth/profile/image/`, `POST auth/profile/change-password/` |
| Users | `GET auth/users/`, `GET/PATCH auth/users/{id}/`, `POST auth/users/{id}/change-password/`, `PATCH/POST auth/users/{id}/status/`, `POST auth/users/bulk-status/` |
| Schools | `GET/POST schools/`, `GET/PATCH/DELETE schools/{id}/`, `PATCH schools/{id}/status/` |
| Academics | All `academics/*` (years, activate, classes, sections, class-sections, holidays, working-days, mark-weekends) — must pass `school` on create |
| Teachers | `GET/POST teachers/`, `POST teachers/bulk-upload/`, `GET/PATCH/PUT/DELETE teachers/{id}/`, `PATCH/POST teachers/{id}/status/`, `POST/DELETE teachers/{id}/class-section/`, `POST teachers/{id}/transfer/` |
| Students | `GET/POST students/`, `POST students/bulk-upload/`, `GET/PATCH/PUT/DELETE students/{id}/`, `PATCH/POST students/{id}/image/` |
| Parents (staff) | `GET/POST parents/`, `POST parents/bulk-upload/`, `GET/PATCH/PUT parents/{id}/`, `POST parents/{id}/reset-password/`, `DELETE parents/{id}/students/{student_id}/` |
| Student attendance | `GET attendance/faces/`, `POST attendance/faces/register/`, `POST attendance/faces/register-from-profile/`, `DELETE attendance/faces/{student_id}/`, `POST attendance/verify/`, `GET/POST attendance/sessions/`, `GET/DELETE attendance/sessions/{id}/`, `PATCH/PUT attendance/sessions/{id}/records/`, `POST .../lock/`, `POST .../unlock/` |
| Teacher attendance | `GET teacher-attendance/records/`, `GET/DELETE .../records/{id}/`, `POST .../records/{id}/verify/`, `GET/PATCH/PUT teacher-attendance/settings/`, `GET teacher-attendance/summary/` |
| Notifications | `GET/POST notifications/`, `GET/DELETE notifications/{id}/`, `GET notifications/{id}/recipients/`, inbox (below) |

### SCHOOL_ADMIN
Same list as SUPER_ADMIN, **scoped to own school**, plus:
- `GET schools/me/`, `PATCH schools/me/logo/`

Not allowed: `schools/` admin routes (`GET/POST schools/`, `schools/{id}/*`).

### TEACHER
| Area | Endpoints |
|---|---|
| Auth/Profile | login, logout, refresh, `auth/profile/*` |
| Self | `GET teachers/me/` |
| Students (own section) | `GET/POST students/`, `POST students/bulk-upload/`, `GET/PATCH/PUT/DELETE students/{id}/`, `PATCH/POST students/{id}/image/` |
| Parents (own section) | `GET/POST parents/`, `POST parents/bulk-upload/`, `GET/PATCH/PUT parents/{id}/`, `POST parents/{id}/reset-password/`, `DELETE parents/{id}/students/{student_id}/` |
| Student attendance | faces (list/register/register-from-profile/delete), `POST attendance/verify/`, sessions list/create/detail, records edit **(DRAFT only)**, `POST .../lock/` (**no unlock**) |
| Own attendance | `POST teacher-attendance/check-in/`, `POST teacher-attendance/check-out/`, `GET teacher-attendance/today/`, `GET teacher-attendance/records/` (own), `GET .../records/{id}/`, `GET teacher-attendance/settings/`, `GET teacher-attendance/summary/` (own) |
| Notifications | `GET/POST notifications/` (to parents of own section only), `GET/DELETE notifications/{id}/`, `GET notifications/{id}/recipients/`, inbox |

Not allowed: academics, teachers admin, schools, users, session unlock, deleting student or teacher attendance, teacher-attendance verify/settings update.

### PARENT
| Area | Endpoints |
|---|---|
| Auth | `POST parents/login/` (phone + password), `POST auth/logout/`, `POST auth/refresh/`, `GET/PATCH auth/profile/`, `POST auth/profile/change-password/` |
| Portal | `GET parents/me/`, `GET parents/me/attendance/`, `GET parents/me/notifications/`, `GET parents/me/notifications/unread-count/`, `POST parents/me/notifications/read/` |
| Inbox | `GET notifications/inbox/`, `GET notifications/inbox/unread-count/`, `POST notifications/inbox/read/`, `GET notifications/inbox/{id}/` |

### Inbox (all roles)
`GET notifications/inbox/`, `GET notifications/inbox/unread-count/`, `POST notifications/inbox/read/`, `GET notifications/inbox/{id}/`

---

## 3. Endpoint details

### 3.1 Accounts — `/api/auth/`

**User object:** `{id, email, name, gender, profile_image, phone_number, role, updated_at, is_active}`

#### POST `/auth/login/` — Public
Staff login with email.
- **Request:** `{ "email": "a@b.com", "password": "..." }`
- **200** `Login successful.` → `{user}` + sets cookies
- **400** `Invalid credentials.` → `{non_field_errors: ["Invalid email or password."]}` `{non_field_errors: ["This account is inactive."]}` (correct password, deactivated account), or field errors.

#### POST `/auth/logout/` — Any logged-in
Blacklists refresh token, clears cookies. No body.
- **200** `Logout successful.` · **401**

#### POST `/auth/refresh/` — Public (needs `refresh_token` cookie)
Rotates tokens, sets new cookies. No body.
- **200** `Token refreshed successfully.`
- **401** `Refresh token cookie is missing.` / token invalid, expired or blacklisted

#### GET `/auth/profile/` — Any logged-in
- **200** `Profile fetched successfully.` → `{user}` · **401**

#### PATCH `/auth/profile/` — Any logged-in
- **Request (all optional):** `name` (≤150), `phone_number` (10 digits), `gender` (MALE/FEMALE/OTHER)
- **200** `Profile updated successfully.` → `{user}`
- **400** `Validation failed.` (e.g. phone format error)

#### PATCH `/auth/profile/image/` — Any logged-in (multipart)
- **Request:** `profile_image` (jpg/jpeg/png/webp)
- **200** `Profile image updated successfully.` → `{user}`
- **400** `Only JPG, PNG, or WEBP image files are allowed.` / `This field is required.` (no file) · **415** for JSON

#### POST `/auth/profile/change-password/` — Any logged-in
- **Request:** `{old_password, new_password, confirm_new_password}`
- **200** `Password changed successfully.`
- **400** `Validation failed.`:
  - `old_password`: "Old password is incorrect."
  - `confirm_new_password`: "New passwords do not match."
  - `new_password`: "Password must be at least 12 characters long." / "...mix of letters, numbers, or symbols." / Django validators

#### GET `/auth/users/` — SA (all), SCH (self + own school's teachers)
- **Query:** `role`, `is_active`, `is_staff`, `is_superuser`, `joined_after/before`, `last_login_after/before`, `search` (name/email/phone), `ordering` (name, email, date_joined, last_login)
- **200** paginated `[user]` · **400** bad filter · **403**

#### GET / PATCH `/auth/users/{id}/` — SA, SCH (scoped)
- PATCH body: `name`, `phone_number`, `gender`
- **200** `User fetched successfully.` / `User updated successfully.` → `{user}`
- **400** `Validation failed.` · **404** `User not found.`

#### POST `/auth/users/{id}/change-password/` — SA, SCH (scoped)
Admin sets someone else's password.
- **Request:** `{new_password, confirm_new_password}`
- **200** `Password changed successfully.` · **400** · **404** `User not found.`

#### PATCH|POST `/auth/users/{id}/status/` — SA, SCH (scoped)
- **Request:** `{ "is_active": true|false }` (deactivating sends an email)
- **200** `User account activated successfully.` / `...deactivated successfully.` / `...is already activated.` → `{user}`
- **400** · **404**

#### POST `/auth/users/bulk-status/` — SA, SCH (scoped)
- **Request:** `{ "user_ids": [1,2,3], "is_active": false }`
- **200** `User accounts updated successfully.` → `{requested, matched, updated, skipped_ids}`. IDs out of scope are skipped silently.
- **400** `This list may not be empty.`

---

### 3.2 Schools — `/api/schools/`

**SchoolDetail:** `{id, name, code, email, phone, address, city, state, country, pincode, logo, status, admin{user}, attendance_threshold, created_at, updated_at}`

#### GET `/schools/` — SA
- **Query:** `status`, `city`, `state`, `search` (name/code/email/phone), `ordering`
- **200** `Schools fetched successfully.` → paginated `[{id, name, code, email, phone, city, state, status, admin_name, attendance_threshold}]`

#### POST `/schools/` — SA
Creates the school and its admin user. Both start **INACTIVE**; no email is sent yet.
- **Request:**
```json
{
  "school": {"name":"", "code":"", "email":"", "phone":"", "address":"", "city":"", "state":"", "country":"", "pincode":"", "attendance_threshold":75},
  "admin":  {"name":"", "email":"", "phone_number":""}
}
```
- **201** `School created successfully.` → SchoolDetail
- **400** `Validation failed.` → `{school:{...}, admin:{...}}` (e.g. "user with this email already exists.")
- **409** `A school with this code already exists.` / `A school with this email already exists.`
- Admin `name`, `email` and `phone_number` are required.

#### GET / PATCH / DELETE `/schools/{id}/` — SA
- PATCH body: any of `name, email, phone, address, city, state, country, pincode, logo, attendance_threshold (1-100)`. `code`, `status` and `admin` cannot be changed.
- **200** `School fetched/updated/deleted successfully.`
- **400** `Validation failed.` · **404** `School not found.`

#### PATCH `/schools/{id}/status/` — SA
Activating sets a new random password for the admin, activates them and **emails the credentials**. Deactivating disables the admin and sends a deactivation email.
- **Request:** `{ "status": "ACTIVE" | "INACTIVE" }`
- **200** `School status updated successfully.` → SchoolDetail
- **400** `"X" is not a valid choice.` · **404**

#### GET `/schools/me/` — SCH
- **200** `School fetched successfully.` · **404** `School not found.`

#### PATCH `/schools/me/logo/` — SCH (multipart)
- **Request:** `logo` (image)
- **200** `School logo updated successfully.` · **400** invalid image · **404**

---

### 3.3 Academics — `/api/academics/` — SA, SCH only (T/P → 403)

For every resource below:
- SA must send `school` on create (years, classes, sections); SCH always uses their own school.
- Details: **404** when not found or out of scope.
- Delete: **200** `X deleted successfully.`, or **409** `X cannot be deleted because it is referenced by other records.`

#### Academic years
| Method & path | Request | Success | Errors |
|---|---|---|---|
| GET `years/` | filters `school, is_active, start_date(__gte/__lte), end_date(...)`, `search` name | 200 `Academic years fetched successfully.` → `[{id, school, school_name, name, start_date, end_date, is_active}]` | — |
| POST `years/` | `{name (≤20), start_date, end_date, school (SA)}` | 201 `Academic year created successfully.` → year detail (with `id`). New years start inactive. | 400 missing school / "End date must be greater than start date." / "The academic year overlaps with an existing academic year for this school." / duplicate name (`non_field_errors`) |
| GET `years/{id}/` | — | 200 `Academic year fetched successfully.` | 404 |
| PUT/PATCH `years/{id}/` | `name, start_date, end_date` | 200 `Academic year updated successfully.` | 400 "End date must be greater than start date." / "The academic year overlaps with an existing academic year for this school." |
| DELETE `years/{id}/` | — | 200 | 409 |
| POST `years/{id}/activate/` | — | 200 `Academic year activated successfully.` (other active years are deactivated) | 404 unknown id or other school's year |

#### Classes / Sections (bulk create)
| Method & path | Request | Success | Errors |
|---|---|---|---|
| GET `classes/`, `sections/` | filter `school`, `search` name | 200 `Classes/Sections fetched successfully.` → `[{id, school, school_name, name}]` | — |
| POST `classes/`, `sections/` | **JSON array** `[{"name":"10", "school":1}]` (school SA only) | **always 200** `Classes/Sections processed successfully.` → `{created:[{id,name}], failed:[{name, error/errors}]}` | 400 `Expected a list of classes.` / `At least one class is required.` · failed entries: "School is required.", "A class with this name already exists." |
| GET/PUT/PATCH/DELETE `.../{id}/` | `{name}` | 200 `Class fetched/updated/deleted successfully.` | 400 duplicate name (`non_field_errors`) · 404 · 409 |

#### Class-sections (year + class + section)
| Method & path | Request | Success | Errors |
|---|---|---|---|
| GET `class-sections/` | filters `academic_year, school_class, section` | 200 → `[{id, academic_year, academic_year_name, school_class, class_name, section, section_name}]` | — |
| POST `class-sections/` | **array** `[{academic_year, school_class, section}]` | 200 `Class-section combinations processed successfully.` → `{created, failed}` | 400 not a list / empty list · failed entries: "The selected class does not belong to the academic year's school.", "This class-section combination already exists.", "You do not have permission to access this academic year." |
| GET/PUT/PATCH/DELETE `class-sections/{id}/` | same fields | 200 | 400 "The class must belong to the same school as the academic year." / "...does not belong to the authorized school." / unique-set error · 404 · 409 |

#### Holidays (kept in sync with a HOLIDAY working-day)
| Method & path | Request | Success | Errors |
|---|---|---|---|
| GET `holidays/` | filters `academic_year, date(__gte/__lte), month`, `search` title/description | 200 `Holidays fetched successfully.` | — |
| POST `holidays/` | `{academic_year, title, date, description?}` | 201 `Holiday created successfully.` → holiday detail (with `id`) | 400 "You do not have permission to access this school's academic data." / "Date must fall within the academic year." / duplicate date |
| GET/PUT/PATCH/DELETE `holidays/{id}/` | same | 200 | 400 validation (date outside year, duplicate, other school's year) · 404 · 409 |

#### Working days (`day_type` = WORKING / HOLIDAY / WEEKEND / EVENT)
| Method & path | Request | Success | Errors |
|---|---|---|---|
| GET `working-days/` | filters `academic_year, date(...), day_type, month` | 200 `Working days fetched successfully.` | — |
| POST `working-days/` | `{academic_year, date, day_type, remarks?}` (HOLIDAY also creates a Holiday) | 201 `Working day created successfully.` → working-day detail (with `id`) | 400 permission/choice / "Date must fall within the academic year." / duplicate date |
| POST `working-days/mark-weekends/` | `{academic_year, weekdays:[0-6] (default [6]=Sunday), start_date?, end_date?, overwrite:false}` | 200 `Weekends marked successfully.` → `{academic_year, weekdays, matched, created, updated, skipped}` | 400 "End date cannot be earlier than start date." / "Date must fall within the academic year." / "End date must be greater than start date." / retry message on race |
| GET/PUT/PATCH/DELETE `working-days/{id}/` | same | 200 | 400 validation · 404 · 409 |

---

### 3.4 Teachers — `/api/teachers/` — SA, SCH (scoped); `me/` is TEACHER only

**TeacherDetail:** `{id, employee_id, name, email, phone_number, gender, is_active, school, school_name, class_section, class_section_detail{...}, joining_date, profile_image, address, city, state, country, pincode, created_at, updated_at}`

#### GET `/teachers/`
- **Query:** `school, class_section, is_active, is_assigned, city, state, joined_after, joined_before`, `search` (employee_id/name/email/phone), `ordering`
- **200** paginated

#### POST `/teachers/`
Creates an **inactive** teacher user; login details are emailed on activation.
- **Request:** `{employee_id*, name*, email*, school* (SA only), phone_number, gender, class_section, address, city, state, country, pincode, joining_date}`
- **201** `Teacher created successfully. Activate the teacher to email their login details.`
- **400**:
  - `email`: "A user with this email address already exists."
  - `employee_id`: "A teacher with this employee ID already exists in this school."
  - `class_section`: "The class section does not belong to this teacher's school."
  - `school`: "This field is required when creating data as a Super Admin."

#### POST `/teachers/bulk-upload/` (multipart)
All rows are validated before anything is created.
- **Request:** `file` (.csv), plus `school` for SA. CSV columns: required `employee_id, name, email`; optional `phone_number, gender, address, city, state, country, pincode, joining_date`. Max 1000 rows.
- **201** `{n} teacher(s) created successfully. Activate them to email their login details.` → `{created, teachers:[...]}`
- **400** `CSV validation failed. No teachers were created.`
  - `errors` = `{file:[...]}`, e.g. "Only CSV files are allowed.", "The CSV file is empty.", "Missing required column(s): ..."
  - or `{"<row>": {field:[...]}}`, e.g. "Email duplicated in this file, first seen on row N."

#### GET / PATCH / PUT / DELETE `/teachers/{id}/`
- PATCH body: profile fields (`class_section` is ignored here; use `/class-section/`)
- **200** `Teacher fetched/updated/deleted successfully.`
- **400** duplicate email/employee_id · **404** `Teacher not found.` · **409** `Teacher cannot be deleted because they are referenced by other records.`

#### PATCH|POST `/teachers/{id}/status/`
- **Request:** `{is_active}`. Activating generates a password and emails it.
- **200** `Teacher activated successfully. Login details have been emailed to them.` / `Teacher deactivated successfully.` / `Teacher is already activated.`
- **400** · **404**

#### POST / DELETE `/teachers/{id}/class-section/`
- POST body: `{class_section}` (assign, replacing any existing one)
- **200** `Class section assigned successfully.` / `Class section revoked successfully.`
- **400** class section from another school · **404** · **409** `This teacher has no class section assigned.` (DELETE)

#### POST `/teachers/{id}/transfer/`
- **Request:** `{class_section}`
- **200** `Teacher transferred successfully.` → `{transferred_from, teacher}`
- **409** `This teacher has no class section to transfer from. Assign one instead.` / `The teacher is already assigned to this class section.`
- **400** · **404**

#### GET `/teachers/me/` — TEACHER
- **200** `Teacher profile fetched successfully.`
- **404** `No teacher profile is linked to this account.`

---

### 3.5 Students — `/api/students/` — SA, SCH, TEACHER (scoped)

**Student:** `{id, student_id, name, roll_number, school, school_name, class_section, class_section_detail, profile_image, has_profile_image, created_at, updated_at}`

Class-section rule:
- **T** never sends one (their own section is used).
- **SCH** sends `class_section`.
- **SA** sends `school` + `class_section`.

#### GET `/students/`
- **Query:** `school, class_section, academic_year, school_class, section, has_profile_image`, `search` (name/student_id/roll_number), `ordering`
- **200** paginated

#### POST `/students/` (JSON or multipart)
- **Request:** `{name*, student_id*, roll_number*, profile_image?, class_section (SCH/SA), school (SA)}`
- **201** `Student enrolled successfully.` → student + `face_job`. With a photo, `face_job` is a [background job](#background-ai-jobs) that checks the photo and registers it as the face; the student is enrolled either way, and a photo the AI rejects is not saved (the job fails with the reason). Without a photo `face_job` is `null`.
- **400**:
  - "A student with this student ID already exists in this school."
  - "A student with this roll number already exists in this class section."
  - "The class section does not belong to a school you administer."
  - "This field is required when acting as a Super Admin."
  - Teacher without a section: "You are not assigned to a class section..."

#### POST `/students/bulk-upload/` (multipart)
- **Request:** `file` (.csv with columns `student_id, name, roll_number`), plus `class_section`/`school` by role. Max 1000 rows.
- **201** `{n} student(s) enrolled successfully.` → `{created, class_section, students}`
- **400** `CSV validation failed. No students were enrolled.` → file errors or per-row errors

#### GET / PATCH / PUT / DELETE `/students/{id}/`
- PATCH body: `name, student_id, roll_number`, plus `class_section` (admins only) to move a student
- **200** `Student fetched/updated/deleted successfully.`
- **400** `No fields were supplied to update.` / duplicate errors
- **404** `Student not found.`
- **409** `Student cannot be deleted because they are referenced by other records.`

#### PATCH|POST `/students/{id}/image/` (multipart)
- **Request:** `profile_image`
- **202** `Photo received. ...` → student (still the old photo) + `face_job`, a [background job](#background-ai-jobs). The new photo is saved once its face is registered; a photo the AI rejects fails the job (`errors.ai_service`) and the old photo and face stay. With the AI service down the photo is saved without a face.
- **400** invalid image · **404** · **409** a photo for this student is still being processed

---

### 3.6 Parents — `/api/parents/`

**Parent (staff view):** `{id, user, name, phone_number, is_active, students:[...], initial_password, password_changed, last_login, created_by, created_at, updated_at}`

#### POST `/parents/login/` — Public
- **Request:** `{ "phone_number": "9876543210", "password": "..." }`
- **200** `Login successful.` → `{user, must_change_password}` + sets the same cookies as staff login
- **400** `Invalid credentials.`:
  - `non_field_errors`: "Invalid mobile number or password."
  - "This account is inactive."
  - phone format error

#### GET `/parents/` — SA, SCH, T (scoped through their children)
- **Query:** `student, class_section, school` (numbers, otherwise 400 "Must be a number."), `search`, `ordering`
- **200** paginated

#### POST `/parents/` — SA, SCH, T
Creates a parent (password `Firstname@NNNN`, returned in `initial_password`) **or** links the student to an existing parent with the same phone.
- **Request:** `{student_id* (school student code), name*, phone_number*, school (SA)}`
- **201** `Parent created successfully.` → `{created: true, ...parent}`
- **200** `A parent with this mobile number already exists ({name}); student {id} was linked to them.` → `{created: false, ...}`
- **400** `student_id`: "No student with this ID in your scope." / `phone_number`: "A parent with this mobile number already exists." / school required (SA)

#### POST `/parents/bulk-upload/` (multipart) — SA, SCH, T
Adds parents from a CSV, one row per child, exactly like calling `POST /parents/` per row: a phone that already belongs to a parent links the child to that account, and the same phone on several rows is one parent with several children.
- **Request:** `file` (.csv with columns `student_id, name, phone_number`; headers are case-insensitive), `school` (SA only, required). Max 1000 rows. Teachers can name only their class's students, School Admins their school's.
- **201** `{c} parent(s) created, {l} child link(s) added to existing parents[, {u} already linked].` → `{created, linked, already_linked, rows: [{row, student_id, student_name, phone_number, parent, created, already_linked}], parents: [...parent incl. initial_password for new ones]}`
- **400** `CSV validation failed. No parents were added.` → `{"file": [...]}` or per-row errors keyed by spreadsheet row number, e.g. `{"3": {"student_id": ["No student with this ID in your scope."]}}`. Row checks: invalid phone, unknown student, the same student + phone repeated, one phone given two different names, phone belonging to a staff account. Nothing is saved if any row fails; re-uploading the same file is safe (rows already linked are counted, not duplicated).

#### GET / PATCH / PUT `/parents/{id}/` — staff
- PATCH body: `name`, `phone_number`
- **200** `Parent fetched/updated successfully.`
- **400** `No fields were supplied to update.` / duplicate phone · **404** `Parent not found.`

#### POST `/parents/{id}/reset-password/` — staff
Generates a new password and returns it in `initial_password`.
- **200** `Parent password reset successfully.` · **404**

#### DELETE `/parents/{id}/students/{student_pk}/` — staff
Unlinks the child. The parent is deleted if they have no children left.
- **200** `Student unlinked from the parent.` / `Student unlinked; the parent had no other children and was deleted.` → `{parent_deleted}`
- **404** `Parent not found.` / `This student is not linked to the parent.`

#### Parent portal — PARENT only
On every portal route, a missing profile returns **404** `No parent profile is linked to your account.`

| Method & path | Request | Success |
|---|---|---|
| GET `me/` | — | 200 `Profile fetched successfully.` → `{id, name, phone_number, students}` |
| GET `me/attendance/` | `student, date, date_from, date_to, status` | 200 paginated `[{id, date, student, student_id, student_name, class_name, section_name, status, remarks}]`, LOCKED sessions only |
| GET `me/notifications/` | `is_read` | 200 paginated attendance alerts `[{id, student, student_name, date, status, title, message, is_read, read_at}]` |
| GET `me/notifications/unread-count/` | — | 200 → `{unread}` |
| POST `me/notifications/read/` | `{ids?: [..]}` (omit to mark all read) | 200 `{n} notification(s) marked as read.` → `{updated}` · 400 if `ids` is empty |
| POST `me/students/{student_pk}/photo/` | multipart `profile_image` | 200 → student + `face_job`. A first photo is just saved (`face_job: null`); once a face is registered, the new photo replaces it through a [background job](#background-ai-jobs). 409 while one is still running. |

---

### 3.7 Student attendance (AI face recognition) — `/api/attendance/` — SA, SCH, TEACHER (scoped)

Lock rule: a **LOCKED** session can only be changed by SA/SCH. A teacher gets **409** `Attendance is locked. Only an admin can change it now.`

#### Background AI jobs

The AI service can take minutes, longer than a production proxy keeps a request open. So every endpoint that waits on it (face registration, attendance verification, student photos) checks the request at once, then queues the AI work and answers **202** with a job to poll:

**AIJob:** `{id (uuid), kind (FACE_REGISTER|FACE_REGISTER_FROM_PROFILE|STUDENT_PHOTO|ATTENDANCE_VERIFY), status (PENDING|RUNNING|SUCCEEDED|FAILED), done, message, total, processed, succeeded, failed, percent, result, error, error_status, errors, poll_after, created_at, started_at, finished_at, updated_at}`

- Poll `GET /attendance/jobs/{id}/` every `poll_after` seconds until `done` is true. `message` says what it is doing now; for batches `processed` / `total` (and the running `result`) grow as it goes.
- **SUCCEEDED:** `result` holds what the endpoint used to answer (per kind below).
- **FAILED:** `error`, `error_status` and `errors` are the message, HTTP status and errors the endpoint would have answered had it done the work inside the request, e.g. `400` + `{"ai_service": "No face detected."}`, `503` AI service unavailable, `409` locked.
- A job whose server stopped (restart, deploy) is reported FAILED with `error_status` 503 once it has been silent for `AI_JOB_STALE_AFTER` seconds (default 20 min). Jobs are deleted after `AI_JOB_RETENTION_DAYS` (default 7).

#### GET `/attendance/jobs/{id}/` — any signed-in user
- **200** → AIJob. Users see only jobs they started; SA sees all.
- **404** `Job not found.`

#### GET `/attendance/faces/`
- **Query:** `school` (SA required), `class_section`, `registered`, `search`
- **200** paginated `[{id, student_id, name, roll_number, profile_image, face_registered, face_source, face_registered_at}]`

#### POST `/attendance/faces/register/` (multipart)
Sends each image to the AI service, in a [background job](#background-ai-jobs). **Bulk:** the filename stem is the student ID (`STU001.jpg`). **Single:** pass `student` with exactly one image.
- **Request:** `images[]` (1–100), `student?`, `school` (SA), `class_section?`
- **202** `Registering {n} face(s) in the background. ...` → AIJob. Its `result`, updated after every image, is `{total, registered, failed, results:[{label, student, student_id, registered, error}]}`; each item's error is in `results`, e.g. "Student not found in your scope.", "no face detected", "Skipped: AI service is unavailable.". A finished job with `registered: 0` registered nothing.
- **400**:
  - `No faces were registered.` → the same summary, when no file names a student in scope (nothing is queued)
  - "Exactly one image is allowed when a student is given."
- **404** `Student not found.`

#### POST `/attendance/faces/register-from-profile/`
Registers faces from students' existing profile images.
- **Request:** `{students?: [ids], only_unregistered: true, school (SA), class_section?}`
- **202** → AIJob, result as for `faces/register/` · **200** `Nothing to register: ...` → empty summary (no job)
- **400** `No faces were registered.` (none of the named students is in scope)

#### DELETE `/attendance/faces/{student_pk}/`
- **200** `Face deleted successfully.` / `No face was registered for this student.`
- **400** AI error (`errors.ai_service`) · **404** `Student not found.` · **503** AI down

#### POST `/attendance/verify/` (multipart)
Classroom photos → AI recognition → saved as a **DRAFT** session. A re-run keeps manual corrections. Recognition runs in a [background job](#background-ai-jobs); the checks below are made before it is queued.
- **Request:** `images[]` (1–5), `date?` (default today), `class_section` (SCH/SA), `school` (SA)
- **202** `Photos received. ...` → AIJob. On success its `result` is `{session: id}`; fetch `GET /attendance/sessions/{id}/` for the detail. AI errors fail the job: `error_status` 400 with `errors.ai_service`, or 503 AI unavailable.
- **400**:
  - "Attendance cannot be marked for a future date."
  - "The date is outside the academic year ..."
  - "{date} is a holiday ({title})."
  - "{date} is not a working day."
  - "This class section has no students."
  - "No student in this class section has a registered face. Register faces before verifying attendance."
- **409** locked · this class section and date is already being verified

#### GET `/attendance/sessions/`
- **Query:** `school, class_section, academic_year, date, date_from, date_to, status (DRAFT|LOCKED), ordering`
- **200** paginated `[{id, school, class_section, class_section_detail, date, status, image_count, detected_faces, total_students, present_count, absent_count, created_by_name, locked_by_name, locked_at, ...}]`

#### POST `/attendance/sessions/` (manual, without AI)
- **Request:** `{date?, class_section (SCH/SA), school (SA), records?: [{student, status: PRESENT|ABSENT, remarks?}]}`. Students not listed are marked ABSENT.
- **201** `Attendance created as draft.`
- **400**:
  - "Attendance for this class section and date already exists. Edit it instead."
  - "Students [ids] are not in this class section."
  - "Student {pk} is listed more than once."
  - date rules (as for verify)

#### GET `/attendance/sessions/{id}/`
- **200** `Attendance fetched successfully.` → list fields + `not_registered_count` + `records:[{id, student, student_id, student_name, roll_number, status, source (AI|MANUAL), ai_status, similarity, face_registered, remarks, updated_by_name}]`
- **404** `Attendance not found.`

#### PATCH|PUT `/attendance/sessions/{id}/records/`
Manual corrections. An admin editing a LOCKED session triggers parent notifications.
- **Request:** `{records: [{student, status, remarks?}]}` (non-empty)
- **200** `Attendance updated successfully.`
- **400** `Student is not part of this attendance.` · **404** · **409** locked (teacher)

#### POST `/attendance/sessions/{id}/lock/` — SA, SCH, T
Finalises the session and notifies parents.
- **200** `Attendance locked successfully.` · **404** · **409** `Attendance is already locked.`

#### POST `/attendance/sessions/{id}/unlock/` — SA, SCH only
- **200** `Attendance unlocked successfully.` · **400** `Attendance is not locked.` · **403** teacher · **404**

#### DELETE `/attendance/sessions/{id}/` — SA, SCH only
Deletes the attendance and all its student records, draft or locked. Parent notifications already sent are kept.
- **200** `Attendance deleted successfully.` → `{id, class_section, date}` · **403** teacher · **404**

---

### 3.8 Teacher attendance — `/api/teacher-attendance/`

**Record:** `{id, teacher, employee_id, teacher_name, school, date, status (DRAFT|VERIFIED), check_in_at, check_out_at, check_in/out_captured_at, check_in/out_verified_at, check_in_image, check_out_image, worked_minutes, worked_hours, day_type (FULL_DAY|HALF_DAY|ABSENT), day_type_overridden, remarks, verified_by_name, verified_at}`

#### POST `/check-in/` and POST `/check-out/` — TEACHER (multipart)
Live camera photo. The server time is what gets recorded.
- **Request:** `image` (jpg/png/webp), `captured_at` (ISO datetime from the device)
- **201** `Checked in successfully. Awaiting school admin verification.` / `Checked out successfully. ...`
- **400**:
  - "The photo must be taken with the camera just before uploading..." (clock skew > 120s)
  - "This photo was not taken just now. Please use the camera."
  - "This photo has already been used..."
  - "The image could not be read."
  - "You have already checked in today."
  - "You have not checked in today."
  - "You have already checked out today."
  - "Today's attendance has already been verified by the school admin."
- **403** non-teacher

#### GET `/today/` — TEACHER
- **200** `Today's attendance fetched successfully.` → record or `null`

#### GET `/records/` — SA, SCH, T (teacher sees only their own)
- **Query:** `school, teacher, date, date_from, date_to, status, day_type, search, ordering`
- **200** paginated

#### GET `/records/{id}/` — SA, SCH, T (scoped)
- **200** `Teacher attendance fetched successfully.` · **404** `Attendance not found.`

#### POST `/records/{id}/verify/` — SA, SCH
Finalises the day. `day_type` is calculated from the school settings unless it is overridden.
- **Request (optional):** `{check_in_time: "HH:MM", check_out_time: "HH:MM", day_type, remarks}`
- **200** `Teacher attendance verified successfully.`
- **400** "The teacher has not checked out. Enter a check-out time to verify this day." / "Check-out must be after check-in."
- **403** teacher · **404**

#### DELETE `/records/{id}/` — SA, SCH only
Deletes the teacher's day, draft or verified, along with its check-in/check-out photos.
- **200** `Teacher attendance deleted successfully.` → `{id, teacher, date}` · **403** teacher · **404**

#### GET `/settings/` — SA, SCH, T · PATCH|PUT `/settings/` — SA, SCH
- **Request:** `school` (SA), `full_day_minutes`, `half_day_minutes` (1–1440). Defaults are 360 and 180.
- **200** `Teacher attendance settings fetched/updated successfully.` → `{school, full_day_minutes, full_day_hours, half_day_minutes, half_day_hours}`
- **400** "A half day must be shorter than a full day." / "This field is required when acting as a Super Admin." / "You are not linked to a school."

#### GET `/summary/` — SA, SCH, T (own)
- **Query:** `school` (SA), `teacher`, `date_from`, `date_to`
- **200** `Teacher attendance summary fetched successfully.` → `{date_from, date_to, teachers:[{teacher, employee_id, teacher_name, total_working_minutes, total_working_hours, total_full_days, total_half_days, total_absent_days, total_working_days, pending_verification}]}`
- **400** "Must be on or after date_from."

---

### 3.9 Notifications — `/api/notifications/`

Who can send to whom:
- **SA:** school admins, teachers and parents (any or chosen schools)
- **SCH:** teachers and parents of own school
- **T:** parents of own section only
- **P:** cannot send (403)

#### GET `/notifications/` — SA, SCH, T (sent/visible)
- **Query:** `search`
- **200** paginated `[{id, title, message, attachments[], sender_name, sender_role, school_name, to_school_admins, to_teachers, to_parents, target_*, recipient_count, read_count, unread_count, created_at}]`

#### POST `/notifications/` — SA, SCH, T (multipart or JSON)
- **Request:**
  - `title*`, `message?`
  - `to_school_admins`, `to_teachers`, `to_parents` (bool)
  - `schools[]` (SA), `class_sections[]` (SA/SCH), `users[]`, `students[]` (sends to their parents)
  - `attachments[]` (≤10 files, ≤50 MB each; executables and scripts are blocked)
- **201** `Notification sent to {n} recipient(s).`
- **400**:
  - "Write a message or attach at least one file."
  - "Choose who should receive this: a group, individual users or students."
  - "You cannot send notifications to this group."
  - "Only a Super Admin can choose schools."
  - "Teachers always send to their own class section."
  - "Students [ids] are outside your scope."
  - "Nobody matches the chosen audience."
  - "<file>: this file type is not allowed." / "larger than N MB."

#### GET `/notifications/{id}/`
- **200** `Notification fetched successfully.` (+ `read_summary` per role) · **404** `Notification not found.`

#### DELETE `/notifications/{id}/` — SA, the sender, or SCH of that school
- **200** `Notification deleted for all recipients.`
- **403** `You cannot delete this notification.` · **404**

#### GET `/notifications/{id}/recipients/`
- **Query:** `is_read`, `role`, `search`
- **200** paginated `[{user:{id, name, role, phone_number, email}, is_read, read_at}]` · **404**

#### Inbox — every logged-in role
| Method & path | Request | Success | Errors |
|---|---|---|---|
| GET `inbox/` | `is_read` | 200 paginated `[{id, title, message, attachments, sender_name, sender_role, school_name, is_read, read_at, created_at}]` | — |
| GET `inbox/unread-count/` | — | 200 → `{unread}` | — |
| POST `inbox/read/` | `{ids?: [..]}` (omit to mark all read) | 200 `{n} notification(s) marked as read.` | 400 empty/invalid `ids` |
| GET `inbox/{id}/` | — | 200 `Notification fetched successfully.` (marks it read) | 404 |

---