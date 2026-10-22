-- A job is claimable only after the scoring API has saved its source locally
-- and transitions it from dispatching to accepted.
create or replace function public.claim_scoring_job(
  p_worker_id text,
  p_lease_seconds int default 90
)
returns public.scoring_jobs
language plpgsql security definer set search_path = public as $$
declare
  v_job public.scoring_jobs;
begin
  if auth.role() <> 'service_role' then
    raise exception 'service_role_required' using errcode = '42501';
  end if;
  if p_worker_id is null or length(trim(p_worker_id)) = 0
     or p_lease_seconds < 30 or p_lease_seconds > 600 then
    raise exception 'invalid_queue_claim';
  end if;

  select *
    into v_job
    from public.scoring_jobs
   where status = 'accepted'
     and (lease_expires_at is null or lease_expires_at <= now())
   order by created_at, id
   for update skip locked
   limit 1;

  if not found then
    return null;
  end if;

  update public.scoring_jobs
     set worker_id = left(trim(p_worker_id), 120),
         claimed_at = now(),
         lease_expires_at = now() + make_interval(secs => p_lease_seconds),
         attempt_count = v_job.attempt_count + 1,
         accepted_at = coalesce(accepted_at, now()),
         updated_at = now()
   where id = v_job.id
   returning * into v_job;
  return v_job;
end $$;

revoke all on function public.claim_scoring_job(text, int) from public, anon, authenticated;
grant execute on function public.claim_scoring_job(text, int) to service_role;
