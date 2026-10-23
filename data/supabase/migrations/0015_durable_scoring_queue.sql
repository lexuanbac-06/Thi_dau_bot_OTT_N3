-- Durable scoring queue metadata. Jobs remain claimable after a scoring
-- process restart, while the lease prevents duplicate local workers.
alter table public.scoring_jobs
  add column if not exists worker_id text,
  add column if not exists claimed_at timestamptz,
  add column if not exists lease_expires_at timestamptz,
  add column if not exists attempt_count int not null default 0,
  add column if not exists benchmark_ids text[];

create index if not exists scoring_jobs_queue_idx
  on public.scoring_jobs (status, created_at)
  where status in ('dispatching', 'accepted', 'running');

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
     set status = 'accepted',
         worker_id = left(trim(p_worker_id), 120),
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

create or replace function public.requeue_expired_scoring_jobs()
returns int
language plpgsql security definer set search_path = public as $$
declare v_count int;
begin
  if auth.role() <> 'service_role' then
    raise exception 'service_role_required' using errcode = '42501';
  end if;
  update public.scoring_jobs
     set status = 'accepted',
         worker_id = null,
         claimed_at = null,
         lease_expires_at = null,
         updated_at = now()
   where status in ('accepted', 'running')
     and lease_expires_at is not null
     and lease_expires_at < now();
  get diagnostics v_count = row_count;
  return v_count;
end $$;

revoke all on function public.requeue_expired_scoring_jobs() from public, anon, authenticated;
grant execute on function public.requeue_expired_scoring_jobs() to service_role;
