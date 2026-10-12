create sequence if not exists public.application_code_seq;

create table if not exists public.users (
  id uuid primary key default gen_random_uuid(),
  full_name text not null,
  email text not null,
  role text not null check (role in ('student', 'staff', 'admin')),
  password_hash text not null,
  session_version integer not null default 0,
  student_id text not null default '',
  program text not null default '',
  year_level text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create unique index if not exists users_active_email_unique
  on public.users (lower(email))
  where deleted_at is null;

create index if not exists users_active_role_created_idx
  on public.users (role, created_at)
  where deleted_at is null;

create table if not exists public.academic_terms (
  id uuid primary key default gen_random_uuid(),
  trimester text not null check (trimester in ('1st Trimester', '2nd Trimester', '3rd Trimester')),
  academic_year text not null check (academic_year ~ '^[0-9]{4}[-–][0-9]{4}$'),
  is_current boolean not null default false,
  created_by_user_id uuid references public.users (id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  unique (trimester, academic_year)
);

create unique index if not exists academic_terms_single_current_idx
  on public.academic_terms (is_current)
  where is_current and deleted_at is null;

create index if not exists academic_terms_active_lookup_idx
  on public.academic_terms (academic_year, trimester)
  where deleted_at is null;

create table if not exists public.applications (
  id uuid primary key default gen_random_uuid(),
  code text not null unique default (
    'APP-' || to_char(now() at time zone 'UTC', 'YYYY') || '-' ||
    lpad(nextval('public.application_code_seq'::regclass)::text, 4, '0')
  ),
  student_user_id uuid not null references public.users (id) on delete restrict,
  student_name text not null,
  student_id text not null default '',
  university_email text not null,
  program text not null,
  year_level text not null,
  gwa numeric(5, 2) not null check (gwa >= 0 and gwa <= 100),
  lowest_grade numeric(5, 2) not null check (lowest_grade >= 0 and lowest_grade <= 100),
  has_failing_grade boolean not null default false,
  has_incomplete_grade boolean not null default false,
  has_dropped_grade boolean not null default false,
  scholarship_type text not null check (scholarship_type in (
    'Academic Scholarship',
    'Entrance Exam Scholarship',
    '4Ps Scholarship',
    'Urdanetarian Scholarship',
    'RPSEA Scholarship',
    'SOC Scholarship',
    'BSA Scholarship',
    'New Program Scholarship'
  )),
  status text not null default 'Submitted' check (status in ('Submitted', 'Under Evaluation', 'Approved', 'Rejected')),
  remarks text not null default '',
  evaluated_by_user_id uuid references public.users (id) on delete set null,
  evaluated_by_name text not null default '',
  discount_percent numeric(5, 2) check (discount_percent is null or (discount_percent >= 0 and discount_percent <= 100)),
  submitted_at timestamptz not null default now(),
  term_id uuid not null references public.academic_terms (id) on delete restrict,
  is_archived boolean not null default false,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create index if not exists applications_active_submitted_idx
  on public.applications (submitted_at desc)
  where deleted_at is null;

create index if not exists applications_active_term_submitted_idx
  on public.applications (term_id, submitted_at desc)
  where deleted_at is null and not is_archived;

create index if not exists applications_active_student_submitted_idx
  on public.applications (student_user_id, submitted_at desc)
  where deleted_at is null;

create table if not exists public.application_files (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications (id) on delete restrict,
  requirement_key text not null check (requirement_key in ('copyOfGrades', 'letterOfIntent', 'notarizedAgreement')),
  original_filename text not null,
  storage_path text not null unique,
  mime_type text not null check (mime_type in ('application/pdf', 'image/jpeg', 'image/png')),
  size_bytes bigint not null check (size_bytes >= 0 and size_bytes <= 5242880),
  uploaded_by_user_id uuid references public.users (id) on delete set null,
  uploaded_at timestamptz not null default now(),
  is_sample boolean not null default false,
  deleted_at timestamptz
);

create unique index if not exists application_files_active_requirement_unique
  on public.application_files (application_id, requirement_key)
  where deleted_at is null;

create index if not exists application_files_active_application_idx
  on public.application_files (application_id)
  where deleted_at is null;

create table if not exists public.application_status_history (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications (id) on delete restrict,
  event_type text not null check (event_type in ('submitted', 'status_changed', 'reopened')),
  from_status text check (from_status is null or from_status in ('Submitted', 'Under Evaluation', 'Approved', 'Rejected')),
  to_status text not null check (to_status in ('Submitted', 'Under Evaluation', 'Approved', 'Rejected')),
  changed_by_user_id uuid references public.users (id) on delete set null,
  changed_by_name text not null,
  remarks text not null default '',
  changed_at timestamptz not null default now()
);

create index if not exists application_status_history_application_idx
  on public.application_status_history (application_id, changed_at);

create table if not exists public.notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.users (id) on delete set null,
  application_id uuid references public.applications (id) on delete set null,
  type text not null check (type in ('status', 'admin')),
  message text not null,
  created_at timestamptz not null default now(),
  is_read boolean not null default false,
  read_at timestamptz,
  deleted_at timestamptz
);

create index if not exists notifications_active_user_date_idx
  on public.notifications (user_id, created_at desc)
  where deleted_at is null;

create index if not exists notifications_active_unread_idx
  on public.notifications (user_id)
  where deleted_at is null and not is_read;

create table if not exists public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  actor_user_id uuid references public.users (id) on delete set null,
  target_user_id uuid references public.users (id) on delete set null,
  action text not null,
  entity_type text not null,
  entity_id uuid,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists audit_logs_entity_created_idx
  on public.audit_logs (entity_type, entity_id, created_at desc);

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists users_touch_updated_at on public.users;
create trigger users_touch_updated_at
before update on public.users
for each row execute function public.touch_updated_at();

drop trigger if exists academic_terms_touch_updated_at on public.academic_terms;
create trigger academic_terms_touch_updated_at
before update on public.academic_terms
for each row execute function public.touch_updated_at();

drop trigger if exists applications_touch_updated_at on public.applications;
create trigger applications_touch_updated_at
before update on public.applications
for each row execute function public.touch_updated_at();

do $$
begin
  if not exists (
    select 1
    from public.academic_terms
    where is_current and deleted_at is null
  ) then
    insert into public.academic_terms (trimester, academic_year, is_current)
    values ('1st Trimester', '2026–2027', true)
    on conflict (trimester, academic_year)
    do update set is_current = true, deleted_at = null;
  end if;
end;
$$;

alter table public.users enable row level security;
alter table public.academic_terms enable row level security;
alter table public.applications enable row level security;
alter table public.application_files enable row level security;
alter table public.application_status_history enable row level security;
alter table public.notifications enable row level security;
alter table public.audit_logs enable row level security;

revoke all on table
  public.users,
  public.academic_terms,
  public.applications,
  public.application_files,
  public.application_status_history,
  public.notifications,
  public.audit_logs
from anon, authenticated;

grant usage on schema public to service_role;
grant select, insert, update, delete on table
  public.users,
  public.academic_terms,
  public.applications,
  public.application_files,
  public.application_status_history,
  public.notifications,
  public.audit_logs
to service_role;

grant usage, select on sequence public.application_code_seq to service_role;
revoke all on sequence public.application_code_seq from anon, authenticated;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'scholarship-documents',
  'scholarship-documents',
  false,
  5242880,
  array['application/pdf', 'image/jpeg', 'image/png']
)
on conflict (id) do update
set name = excluded.name,
    public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

create or replace function public.admin_update_account(
  p_actor_user_id uuid,
  p_target_user_id uuid,
  p_full_name text,
  p_email text,
  p_role text,
  p_password_hash text default null
)
returns jsonb
language plpgsql
set search_path = public, pg_temp
as $$
declare
  actor_row public.users%rowtype;
  target_row public.users%rowtype;
  updated_row public.users%rowtype;
  active_admin_count integer;
begin
  perform pg_advisory_xact_lock(7310492026);

  select * into actor_row
  from public.users
  where id = p_actor_user_id and deleted_at is null
  for update;

  if not found or actor_row.role <> 'admin' then
    raise exception 'Only an Admin can edit accounts.';
  end if;

  select * into target_row
  from public.users
  where id = p_target_user_id and deleted_at is null
  for update;

  if not found then
    raise exception 'Account not found.';
  end if;

  if p_role not in ('student', 'staff', 'admin') then
    raise exception 'Invalid role.';
  end if;

  if p_target_user_id = p_actor_user_id and p_role <> target_row.role then
    raise exception 'You cannot change your own role.';
  end if;

  if target_row.role = 'admin' and p_role <> 'admin' then
    select count(*) into active_admin_count
    from public.users
    where role = 'admin' and deleted_at is null;

    if active_admin_count <= 1 then
      raise exception 'There must be at least one Admin account.';
    end if;
  end if;

  if exists (
    select 1 from public.users
    where lower(email) = lower(btrim(p_email))
      and id <> p_target_user_id
      and deleted_at is null
  ) then
    raise exception 'An account with this email already exists.';
  end if;

  update public.users
  set full_name = btrim(p_full_name),
      email = lower(btrim(p_email)),
      role = p_role,
      password_hash = coalesce(nullif(p_password_hash, ''), password_hash),
      session_version = case
        when nullif(p_password_hash, '') is not null then session_version + 1
        else session_version
      end
  where id = p_target_user_id
  returning * into updated_row;

  insert into public.audit_logs (actor_user_id, target_user_id, action, entity_type, entity_id, details)
  values (
    p_actor_user_id,
    p_target_user_id,
    'account_updated',
    'user',
    p_target_user_id,
    jsonb_build_object(
      'before', jsonb_build_object('full_name', target_row.full_name, 'email', target_row.email, 'role', target_row.role),
      'after', jsonb_build_object('full_name', updated_row.full_name, 'email', updated_row.email, 'role', updated_row.role)
    )
  );

  return to_jsonb(updated_row) - 'password_hash';
end;
$$;

create or replace function public.admin_delete_account(
  p_actor_user_id uuid,
  p_target_user_id uuid
)
returns jsonb
language plpgsql
set search_path = public, pg_temp
as $$
declare
  actor_row public.users%rowtype;
  target_row public.users%rowtype;
  active_admin_count integer;
begin
  perform pg_advisory_xact_lock(7310492026);

  select * into actor_row
  from public.users
  where id = p_actor_user_id and deleted_at is null
  for update;

  if not found or actor_row.role <> 'admin' then
    raise exception 'Only an Admin can delete accounts.';
  end if;

  if p_target_user_id = p_actor_user_id then
    raise exception 'You cannot delete your own account.';
  end if;

  select * into target_row
  from public.users
  where id = p_target_user_id and deleted_at is null
  for update;

  if not found then
    raise exception 'Account not found.';
  end if;

  if target_row.role = 'admin' then
    select count(*) into active_admin_count
    from public.users
    where role = 'admin' and deleted_at is null;

    if active_admin_count <= 1 then
      raise exception 'There must be at least one Admin account.';
    end if;
  end if;

  update public.users
  set deleted_at = now()
  where id = p_target_user_id;

  update public.notifications
  set deleted_at = now()
  where user_id = p_target_user_id and deleted_at is null;

  insert into public.audit_logs (actor_user_id, target_user_id, action, entity_type, entity_id, details)
  values (
    p_actor_user_id,
    p_target_user_id,
    'account_deleted',
    'user',
    p_target_user_id,
    jsonb_build_object('full_name', target_row.full_name, 'email', target_row.email, 'role', target_row.role)
  );

  return jsonb_build_object('id', p_target_user_id, 'deleted', true);
end;
$$;

create or replace function public.set_current_term(
  p_actor_user_id uuid,
  p_trimester text,
  p_academic_year text
)
returns jsonb
language plpgsql
set search_path = public, pg_temp
as $$
declare
  actor_row public.users%rowtype;
  old_term public.academic_terms%rowtype;
  new_term public.academic_terms%rowtype;
  archived_count integer;
  new_label text;
begin
  perform pg_advisory_xact_lock(7310492027);

  select * into actor_row
  from public.users
  where id = p_actor_user_id and deleted_at is null
  for update;

  if not found or actor_row.role not in ('staff', 'admin') then
    raise exception 'Only Authorized Staff or Admin can change the term.';
  end if;

  if p_trimester not in ('1st Trimester', '2nd Trimester', '3rd Trimester') then
    raise exception 'Please choose the 1st, 2nd or 3rd Trimester.';
  end if;

  if p_academic_year !~ '^[0-9]{4}[-/–][0-9]{4}$' then
    raise exception 'Academic year must be two years like 2026-2027.';
  end if;

  if substring(p_academic_year from 1 for 4)::integer < 2000
     or substring(p_academic_year from 1 for 4)::integer > 2100
     or substring(p_academic_year from 6 for 4)::integer <>
        substring(p_academic_year from 1 for 4)::integer + 1 then
    raise exception 'The second year must follow the first and the academic year must be between 2000 and 2100.';
  end if;

  select * into old_term
  from public.academic_terms
  where is_current and deleted_at is null
  for update;

  if not found then
    raise exception 'No active academic term is configured.';
  end if;

  if old_term.trimester = p_trimester
     and replace(old_term.academic_year, '-', '–') = replace(p_academic_year, '-', '–') then
    raise exception 'The system is already on % , AY %. Nothing was changed.', p_trimester, p_academic_year;
  end if;

  update public.applications
  set is_archived = true,
      archived_at = coalesce(archived_at, now())
  where term_id = old_term.id
    and not is_archived
    and deleted_at is null;

  get diagnostics archived_count = row_count;

  update public.academic_terms
  set is_current = false
  where id = old_term.id;

  insert into public.academic_terms (trimester, academic_year, is_current, created_by_user_id, deleted_at)
  values (p_trimester, replace(p_academic_year, '-', '–'), true, p_actor_user_id, null)
  on conflict (trimester, academic_year)
  do update set is_current = true,
                created_by_user_id = excluded.created_by_user_id,
                deleted_at = null
  returning * into new_term;

  new_label := new_term.trimester || ', AY ' || new_term.academic_year;

  insert into public.audit_logs (actor_user_id, action, entity_type, entity_id, details)
  values (
    p_actor_user_id,
    'academic_term_changed',
    'academic_term',
    new_term.id,
    jsonb_build_object(
      'previous_label', old_term.trimester || ', AY ' || old_term.academic_year,
      'label', new_label,
      'archived_applications', archived_count
    )
  );

  return jsonb_build_object(
    'label', new_label,
    'previousLabel', old_term.trimester || ', AY ' || old_term.academic_year,
    'archived', archived_count
  );
end;
$$;

create or replace function public.transition_application_status(
  p_actor_user_id uuid,
  p_application_id uuid,
  p_status text,
  p_remarks text default '',
  p_discount_percent numeric default null
)
returns jsonb
language plpgsql
set search_path = public, pg_temp
as $$
declare
  actor_row public.users%rowtype;
  application_row public.applications%rowtype;
  updated_row public.applications%rowtype;
  note_text text;
  message_text text;
begin
  select * into actor_row
  from public.users
  where id = p_actor_user_id and deleted_at is null;

  if not found or actor_row.role not in ('staff', 'admin') then
    raise exception 'Only Authorized Staff or Admin can evaluate applications.';
  end if;

  select * into application_row
  from public.applications
  where id = p_application_id and deleted_at is null
  for update;

  if not found then
    raise exception 'Application not found.';
  end if;

  if application_row.is_archived then
    raise exception 'This application belongs to a past term and can no longer be evaluated.';
  end if;

  if not (
    (application_row.status = 'Submitted' and p_status = 'Under Evaluation') or
    (application_row.status = 'Under Evaluation' and p_status in ('Approved', 'Rejected'))
  ) then
    raise exception 'An application cannot move from % to %.', application_row.status, p_status;
  end if;

  note_text := btrim(coalesce(p_remarks, ''));

  if p_status = 'Rejected' and note_text = '' then
    raise exception 'Remarks are required to reject an application.';
  end if;

  if p_discount_percent is not null and (p_discount_percent < 0 or p_discount_percent > 100) then
    raise exception 'Discount percentage must be a number between 0 and 100.';
  end if;

  update public.applications
  set status = p_status,
      remarks = note_text,
      evaluated_by_user_id = p_actor_user_id,
      evaluated_by_name = actor_row.full_name,
      discount_percent = case
        when p_status = 'Approved' and p_discount_percent is not null then p_discount_percent
        else discount_percent
      end
  where id = p_application_id
  returning * into updated_row;

  insert into public.application_status_history (
    application_id, event_type, from_status, to_status, changed_by_user_id, changed_by_name, remarks
  )
  values (
    p_application_id, 'status_changed', application_row.status, p_status,
    p_actor_user_id, actor_row.full_name, note_text
  );

  message_text := 'Your ' || application_row.scholarship_type || ' application (' || application_row.code || ')';

  if p_status = 'Under Evaluation' then
    message_text := message_text || ' moved to Under Evaluation.';
  elsif p_status = 'Approved' then
    message_text := message_text || ' was Approved.' ||
      case when note_text <> '' then ' Remarks: ' || note_text else '' end ||
      ' Please proceed to the CSS Office for the next steps.';
  else
    message_text := message_text || ' was Rejected. Reason: ' || note_text ||
      ' You may visit the CSS Office if you need clarification.';
  end if;

  insert into public.notifications (user_id, application_id, type, message)
  values (application_row.student_user_id, p_application_id, 'status', message_text);

  return to_jsonb(updated_row);
end;
$$;

create or replace function public.reopen_application(
  p_admin_user_id uuid,
  p_application_id uuid,
  p_reason text
)
returns jsonb
language plpgsql
set search_path = public, pg_temp
as $$
declare
  admin_row public.users%rowtype;
  application_row public.applications%rowtype;
  updated_row public.applications%rowtype;
  reason_text text;
begin
  select * into admin_row
  from public.users
  where id = p_admin_user_id and deleted_at is null;

  if not found or admin_row.role <> 'admin' then
    raise exception 'Only an Admin can reopen a decided application.';
  end if;

  select * into application_row
  from public.applications
  where id = p_application_id and deleted_at is null
  for update;

  if not found then
    raise exception 'Application not found.';
  end if;

  if application_row.is_archived then
    raise exception 'This application belongs to a past term and can no longer be changed.';
  end if;

  if application_row.status not in ('Approved', 'Rejected') then
    raise exception 'Only an approved or rejected application can be reopened.';
  end if;

  reason_text := btrim(coalesce(p_reason, ''));

  if reason_text = '' then
    raise exception 'A reason is required to reopen an application.';
  end if;

  update public.applications
  set status = 'Under Evaluation',
      remarks = '',
      evaluated_by_user_id = null,
      evaluated_by_name = '',
      discount_percent = null
  where id = p_application_id
  returning * into updated_row;

  insert into public.application_status_history (
    application_id, event_type, from_status, to_status, changed_by_user_id, changed_by_name, remarks
  )
  values (
    p_application_id, 'reopened', application_row.status, 'Under Evaluation',
    p_admin_user_id, admin_row.full_name,
    'Reopened (was ' || application_row.status || '): ' || reason_text
  );

  insert into public.notifications (user_id, application_id, type, message)
  values (
    application_row.student_user_id,
    p_application_id,
    'status',
    'Your ' || application_row.scholarship_type || ' application (' || application_row.code ||
      ') was reopened and is Under Evaluation again. Reason: ' || reason_text
  );

  return to_jsonb(updated_row);
end;
$$;

revoke execute on function public.admin_update_account(uuid, uuid, text, text, text, text) from public, anon, authenticated;
revoke execute on function public.admin_delete_account(uuid, uuid) from public, anon, authenticated;
revoke execute on function public.set_current_term(uuid, text, text) from public, anon, authenticated;
revoke execute on function public.transition_application_status(uuid, uuid, text, text, numeric) from public, anon, authenticated;
revoke execute on function public.reopen_application(uuid, uuid, text) from public, anon, authenticated;
grant execute on function public.admin_update_account(uuid, uuid, text, text, text, text) to service_role;
grant execute on function public.admin_delete_account(uuid, uuid) to service_role;
grant execute on function public.set_current_term(uuid, text, text) to service_role;
grant execute on function public.transition_application_status(uuid, uuid, text, text, numeric) to service_role;
grant execute on function public.reopen_application(uuid, uuid, text) to service_role;

create or replace function public.update_application_discount(
  p_actor_user_id uuid,
  p_application_id uuid,
  p_discount_percent numeric
)
returns jsonb
language plpgsql
set search_path = public, pg_temp
as $$
declare
  actor_row public.users%rowtype;
  application_row public.applications%rowtype;
  updated_row public.applications%rowtype;
begin
  select * into actor_row
  from public.users
  where id = p_actor_user_id and deleted_at is null;

  if not found or actor_row.role not in ('staff', 'admin') then
    raise exception 'Only Authorized Staff or Admin can edit the tuition fee discount.';
  end if;

  select * into application_row
  from public.applications
  where id = p_application_id and deleted_at is null
  for update;

  if not found then
    raise exception 'Application not found.';
  end if;

  if application_row.is_archived then
    raise exception 'Applications from past terms are locked.';
  end if;

  if application_row.status <> 'Approved' then
    raise exception 'Only approved applications have a tuition fee discount to edit.';
  end if;

  if p_discount_percent is not null and (p_discount_percent < 0 or p_discount_percent > 100) then
    raise exception 'Discount percentage must be a number between 0 and 100.';
  end if;

  update public.applications
  set discount_percent = p_discount_percent
  where id = p_application_id
  returning * into updated_row;

  return to_jsonb(updated_row);
end;
$$;

revoke execute on function public.update_application_discount(uuid, uuid, numeric) from public, anon, authenticated;
grant execute on function public.update_application_discount(uuid, uuid, numeric) to service_role;

create or replace function public.ensure_application_current_term()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
  perform 1
  from public.academic_terms
  where id = new.term_id
    and is_current
    and deleted_at is null
  for share;

  if not found then
    raise exception 'Applications can only be submitted for the current academic term.';
  end if;
  return new;
end;
$$;

drop trigger if exists applications_current_term_guard on public.applications;
create trigger applications_current_term_guard
before insert on public.applications
for each row execute function public.ensure_application_current_term();
