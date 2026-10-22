-- Scoring jobs are created by the authenticated contestant and completed only
-- by the trusted self-hosted scoring module (service_role).
create table if not exists public.scoring_jobs (
  id             uuid primary key,
  user_id        uuid not null references public.profiles(id) on delete cascade,
  kind           text not null check (kind in ('entry', 'submission', 'test')),
  rnd            int,
  day            int,
  status         text not null default 'dispatching'
                   check (status in ('dispatching', 'accepted', 'running', 'succeeded', 'failed', 'timed_out', 'dispatch_failed')),
  sha256         text,
  size_bytes     int check (size_bytes is null or size_bytes between 1 and 65536),
  result         jsonb,
  error_code     text,
  error_message  text,
  created_at     timestamptz not null default now(),
  accepted_at    timestamptz,
  started_at     timestamptz,
  finished_at    timestamptz,
  updated_at     timestamptz not null default now(),
  check ((kind = 'test') or (sha256 is not null and size_bytes is not null)),
  check ((kind <> 'submission') or (rnd is not null and day is not null))
);

create index if not exists scoring_jobs_user_created_idx
  on public.scoring_jobs (user_id, created_at desc);
create index if not exists scoring_jobs_status_created_idx
  on public.scoring_jobs (status, created_at);

alter table public.submissions add column if not exists scoring_job_id uuid references public.scoring_jobs(id);

alter table public.scoring_jobs enable row level security;
drop policy if exists scoring_jobs_self_read on public.scoring_jobs;
create policy scoring_jobs_self_read on public.scoring_jobs
  for select to authenticated using (user_id = auth.uid() or public.is_admin());
revoke all on public.scoring_jobs from anon, authenticated;
grant select on public.scoring_jobs to authenticated;

create or replace function public.create_scoring_job(
  p_job_id uuid,
  p_kind text,
  p_rnd int,
  p_day int,
  p_sha256 text,
  p_size_bytes int
)
returns public.scoring_jobs
language plpgsql security definer set search_path = public as $$
declare
  v_job public.scoring_jobs;
  v_profile public.profiles;
  v_state public.tournament_state;
begin
  if auth.uid() is null then raise exception 'authentication_required' using errcode = '28000'; end if;
  if p_kind not in ('entry', 'submission', 'test') then raise exception 'invalid_job_kind' using errcode = '22023'; end if;
  if p_size_bytes is not null and (p_size_bytes < 1 or p_size_bytes > 65536) then
    raise exception 'file_too_large' using errcode = '22023';
  end if;
  if p_kind <> 'test' and (p_sha256 is null or p_sha256 !~ '^[0-9a-f]{64}$' or p_size_bytes is null) then
    raise exception 'invalid_file_metadata' using errcode = '22023';
  end if;

  select * into v_profile from public.profiles where id = auth.uid();
  if not found or v_profile.status = 'banned' then raise exception 'account_not_allowed' using errcode = '42501'; end if;

  if p_kind in ('entry', 'submission') then
    select * into v_state from public.tournament_state where id = 1;
    if not found or not v_state.accepting_submissions then raise exception 'submissions_closed' using errcode = '55000'; end if;
    if p_kind = 'entry' and v_state.phase <> 'entry' then raise exception 'entry_closed' using errcode = '55000'; end if;
    if p_kind = 'submission' and (v_state.phase <> 'round' or v_state.current_round <> p_rnd or v_state.current_day <> p_day) then
      raise exception 'submission_context_stale' using errcode = '55000';
    end if;
    if p_kind = 'entry' and v_profile.status <> 'new' then
      raise exception 'entry_not_allowed' using errcode = '42501';
    end if;
    if p_kind = 'submission' and v_profile.role <> 'admin' and (
      v_profile.status <> 'active'
      or not exists (select 1 from public.round_members rm where rm.rnd = p_rnd and rm.user_id = auth.uid())
      or exists (select 1 from public.round_config rc where rc.rnd = p_rnd and rc.is_offline)
    ) then
      raise exception 'submission_not_allowed' using errcode = '42501';
    end if;
  end if;

  insert into public.scoring_jobs(id, user_id, kind, rnd, day, sha256, size_bytes)
  values (p_job_id, auth.uid(), p_kind, p_rnd, p_day, p_sha256, p_size_bytes)
  returning * into v_job;
  return v_job;
exception when unique_violation then
  select * into v_job from public.scoring_jobs where id = p_job_id and user_id = auth.uid();
  if found then return v_job; end if;
  raise;
end $$;

create or replace function public.mark_scoring_job_accepted(p_job_id uuid)
returns boolean language plpgsql security definer set search_path = public as $$
begin
  update public.scoring_jobs set status = 'accepted', accepted_at = coalesce(accepted_at, now()), updated_at = now()
  where id = p_job_id and status = 'dispatching';
  return found;
end $$;

create or replace function public.mark_scoring_job_running(p_job_id uuid)
returns boolean language plpgsql security definer set search_path = public as $$
begin
  update public.scoring_jobs set status = 'running', started_at = coalesce(started_at, now()), updated_at = now()
  where id = p_job_id and status in ('dispatching', 'accepted');
  return found;
end $$;

create or replace function public.complete_scoring_job(p_job_id uuid, p_result jsonb)
returns boolean language plpgsql security definer set search_path = public as $$
declare
  v_job public.scoring_jobs;
begin
  select * into v_job from public.scoring_jobs where id = p_job_id for update;
  if not found or v_job.status not in ('dispatching', 'accepted', 'running') then return false; end if;
  update public.scoring_jobs set status = 'succeeded', result = p_result,
    finished_at = now(), updated_at = now(), error_code = null, error_message = null
    where id = p_job_id;

  if v_job.kind = 'entry' then
    update public.profiles set entry_score = (p_result->>'converted_score')::numeric,
      status = case when coalesce((p_result->>'passed')::boolean, false) then 'active'::public.user_status else 'new'::public.user_status end
    where id = v_job.user_id and status = 'new';
  elsif v_job.kind = 'submission' then
    insert into public.submissions(user_id, rnd, day, submitted_at, sha256, size_bytes, scoring_job_id)
    values (v_job.user_id, v_job.rnd, v_job.day, now(), v_job.sha256, v_job.size_bytes, v_job.id)
    on conflict (user_id, rnd, day) do update set submitted_at = excluded.submitted_at,
      sha256 = excluded.sha256, size_bytes = excluded.size_bytes, scoring_job_id = excluded.scoring_job_id;
  end if;
  return true;
end $$;

create or replace function public.fail_scoring_job(p_job_id uuid, p_error_code text, p_error_message text default null)
returns boolean language plpgsql security definer set search_path = public as $$
begin
  update public.scoring_jobs set status = 'failed', error_code = left(p_error_code, 80),
    error_message = left(p_error_message, 500), finished_at = now(), updated_at = now()
  where id = p_job_id and status in ('dispatching', 'accepted', 'running');
  return found;
end $$;

create or replace function public.fail_scoring_dispatch(p_job_id uuid)
returns boolean language plpgsql security definer set search_path = public as $$
begin
  update public.scoring_jobs set status = 'dispatch_failed', error_code = 'module_unavailable',
    error_message = 'Scoring module did not accept the request.', finished_at = now(), updated_at = now()
  where id = p_job_id and user_id = auth.uid() and status = 'dispatching';
  return found;
end $$;

create or replace function public.timeout_scoring_jobs(p_before timestamptz)
returns int language plpgsql security definer set search_path = public as $$
declare v_count int;
begin
  update public.scoring_jobs set status = 'timed_out', error_code = 'scoring_timeout',
    error_message = 'Scoring exceeded the allowed time.', finished_at = now(), updated_at = now()
  where status in ('dispatching', 'accepted', 'running') and coalesce(started_at, accepted_at, created_at) < p_before;
  get diagnostics v_count = row_count;
  return v_count;
end $$;

revoke all on function public.create_scoring_job(uuid,text,int,int,text,int) from public, anon;
revoke all on function public.mark_scoring_job_accepted(uuid) from public, anon, authenticated;
revoke all on function public.mark_scoring_job_running(uuid) from public, anon, authenticated;
revoke all on function public.complete_scoring_job(uuid,jsonb) from public, anon, authenticated;
revoke all on function public.fail_scoring_job(uuid,text,text) from public, anon, authenticated;
revoke all on function public.fail_scoring_dispatch(uuid) from public, anon;
revoke all on function public.timeout_scoring_jobs(timestamptz) from public, anon, authenticated;
grant execute on function public.create_scoring_job(uuid,text,int,int,text,int) to authenticated;
grant execute on function public.fail_scoring_dispatch(uuid) to authenticated;
grant execute on function public.mark_scoring_job_accepted(uuid) to service_role;
grant execute on function public.mark_scoring_job_running(uuid) to service_role;
grant execute on function public.complete_scoring_job(uuid,jsonb) to service_role;
grant execute on function public.fail_scoring_job(uuid,text,text) to service_role;
grant execute on function public.timeout_scoring_jobs(timestamptz) to service_role;

create or replace function public.get_my_replay_matches()
returns table (
  match_id bigint,
  rnd int,
  day int,
  rd int,
  grp int,
  player_a text,
  player_b text,
  score_a smallint
)
language sql stable security definer set search_path = public as $$
  select m.id, m.rnd, m.day, m.rd, m.grp, pa.username, pb.username, m.score_a
  from public.matches m
  join public.profiles pa on pa.id = m.player_a
  join public.profiles pb on pb.id = m.player_b
  join public.contest_days cd on cd.rnd = m.rnd and cd.day = m.day and cd.state = 'graded'
  where m.has_replay
    and (public.is_admin() or exists (
      select 1 from public.round_members me
      where me.user_id = auth.uid() and me.rnd = m.rnd and me.grp = m.grp
    ))
  order by m.rnd desc, m.day desc, m.rd, pa.username
$$;
revoke all on function public.get_my_replay_matches() from public, anon;
grant execute on function public.get_my_replay_matches() to authenticated;
