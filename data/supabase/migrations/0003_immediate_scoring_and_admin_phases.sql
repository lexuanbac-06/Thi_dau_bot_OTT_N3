-- Immediate scoring: each bot upload creates one auditable scoring job.
-- During the entry/qualification phase, each contestant gets at most 20
-- non-dispatch-failed attempts. The best completed score is kept on profile.

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
  v_attempts int;
begin
  if auth.uid() is null then raise exception 'authentication_required' using errcode = '28000'; end if;
  if p_kind not in ('entry', 'test') then raise exception 'invalid_job_kind' using errcode = '22023'; end if;
  if p_size_bytes is null or p_size_bytes < 1 or p_size_bytes > 65536
     or p_sha256 is null or p_sha256 !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid_file_metadata' using errcode = '22023';
  end if;

  -- Serialize per-user job creation so parallel clicks cannot exceed the cap.
  select * into v_profile from public.profiles where id = auth.uid() for update;
  if not found or v_profile.status = 'banned' then raise exception 'account_not_allowed' using errcode = '42501'; end if;
  select * into v_state from public.tournament_state where id = 1;
  if not found or not v_state.accepting_submissions or v_state.phase = 'done' then
    raise exception 'submissions_closed' using errcode = '55000';
  end if;

  if p_kind = 'entry' and v_state.phase = 'entry' then
    select count(*) into v_attempts from public.scoring_jobs
      where user_id = auth.uid() and kind = 'entry' and status <> 'dispatch_failed';
    if v_attempts >= 20 then raise exception 'qualification_attempt_limit' using errcode = '54000'; end if;
  end if;

  insert into public.scoring_jobs(id, user_id, kind, rnd, day, sha256, size_bytes)
  values (p_job_id, auth.uid(), p_kind, null, null, p_sha256, p_size_bytes)
  returning * into v_job;
  return v_job;
exception when unique_violation then
  select * into v_job from public.scoring_jobs where id = p_job_id and user_id = auth.uid();
  if found then return v_job; end if;
  raise;
end $$;

create or replace function public.complete_scoring_job(p_job_id uuid, p_result jsonb)
returns boolean language plpgsql security definer set search_path = public as $$
declare
  v_job public.scoring_jobs;
  v_score numeric;
begin
  select * into v_job from public.scoring_jobs where id = p_job_id for update;
  if not found or v_job.status not in ('dispatching', 'accepted', 'running') then return false; end if;
  update public.scoring_jobs set status = 'succeeded', result = p_result,
    finished_at = now(), updated_at = now(), error_code = null, error_message = null
    where id = p_job_id;

  if v_job.kind = 'entry' then
    v_score := (p_result->>'converted_score')::numeric;
    if v_score is not null then
      update public.profiles set entry_score = v_score,
        status = case when coalesce((p_result->>'passed')::boolean, false)
                      then 'active'::public.user_status else 'new'::public.user_status end
      where id = v_job.user_id and (entry_score is null or v_score > entry_score);
    end if;
  end if;
  return true;
end $$;

create or replace function public.set_tournament_phase(p_phase public.tour_phase, p_accepting boolean)
returns public.tournament_state
language plpgsql security definer set search_path = public as $$
declare v_state public.tournament_state;
begin
  if not public.is_admin() then raise exception 'admin_required' using errcode = '42501'; end if;
  update public.tournament_state set phase = p_phase,
    accepting_submissions = case when p_phase = 'done' then false else p_accepting end,
    updated_at = now()
  where id = 1 returning * into v_state;
  return v_state;
end $$;

revoke all on function public.create_scoring_job(uuid,text,int,int,text,int) from public, anon;
grant execute on function public.create_scoring_job(uuid,text,int,int,text,int) to authenticated;
revoke all on function public.complete_scoring_job(uuid,jsonb) from public, anon, authenticated;
grant execute on function public.complete_scoring_job(uuid,jsonb) to service_role;
revoke all on function public.set_tournament_phase(public.tour_phase,boolean) from public, anon, authenticated;
grant execute on function public.set_tournament_phase(public.tour_phase,boolean) to authenticated;
