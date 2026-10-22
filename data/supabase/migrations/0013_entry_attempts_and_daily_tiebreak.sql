-- Enforce the qualification attempt cap in the database and keep the best
-- weighted score until admins close qualification. Day ranks use the actual
-- opening order for that day as the final tie-break.

create or replace function public.create_scoring_job(
  p_job_id uuid, p_kind text, p_rnd int, p_day int, p_sha256 text, p_size_bytes int
)
returns public.scoring_jobs
language plpgsql security definer set search_path = public as $$
declare
  v_job public.scoring_jobs;
  v_profile public.profiles;
  v_state public.tournament_state;
  v_attempts int;
begin
  if auth.uid() is null then raise exception 'authentication_required' using errcode='28000'; end if;
  if p_kind not in ('entry','submission','test') then raise exception 'invalid_job_kind' using errcode='22023'; end if;
  if p_size_bytes is not null and (p_size_bytes<1 or p_size_bytes>65536) then raise exception 'file_too_large' using errcode='22023'; end if;
  if p_kind<>'test' and (p_sha256 is null or p_sha256 !~ '^[0-9a-f]{64}$' or p_size_bytes is null) then
    raise exception 'invalid_file_metadata' using errcode='22023';
  end if;
  if p_kind in ('entry','submission') then
    select * into v_state from public.tournament_state ts where ts.id=1 for share;
    if not found or not v_state.accepting_submissions then raise exception 'submissions_closed' using errcode='55000'; end if;
  end if;
  select * into v_profile from public.profiles p where p.id=auth.uid() for update;
  if not found or v_profile.status in ('banned','out') then raise exception 'account_not_allowed' using errcode='42501'; end if;

  if p_kind in ('entry','submission') then
    if p_kind='entry' then
      if v_state.phase<>'entry' then raise exception 'entry_closed' using errcode='55000'; end if;
      if v_profile.status not in ('new','active') then raise exception 'entry_not_allowed' using errcode='42501'; end if;
      select count(*)::int into v_attempts from public.scoring_jobs sj
        where sj.user_id=auth.uid() and sj.kind='entry' and sj.status<>'dispatch_failed';
      if v_attempts>=20 then raise exception 'qualification_attempt_limit' using errcode='55000'; end if;
    else
      if v_state.phase<>'round' or v_state.current_round<>p_rnd or v_state.current_day<>p_day then
        raise exception 'submission_context_stale' using errcode='55000';
      end if;
      if v_profile.role<>'admin' and (v_profile.status<>'active'
        or not exists(select 1 from public.round_members rm where rm.rnd=p_rnd and rm.user_id=auth.uid())
        or exists(select 1 from public.round_config rc where rc.rnd=p_rnd and rc.is_offline)) then
        raise exception 'submission_not_allowed' using errcode='42501';
      end if;
    end if;
  end if;

  insert into public.scoring_jobs(id,user_id,kind,rnd,day,sha256,size_bytes)
    values(p_job_id,auth.uid(),p_kind,p_rnd,p_day,p_sha256,p_size_bytes) returning * into v_job;
  return v_job;
exception when unique_violation then
  select * into v_job from public.scoring_jobs sj where sj.id=p_job_id and sj.user_id=auth.uid();
  if found then return v_job; end if;
  raise;
end $$;
revoke all on function public.create_scoring_job(uuid,text,int,int,text,int) from public,anon;
grant execute on function public.create_scoring_job(uuid,text,int,int,text,int) to authenticated;

create or replace function public.complete_scoring_job(p_job_id uuid,p_result jsonb)
returns boolean language plpgsql security definer set search_path = public as $$
declare v_job public.scoring_jobs;
begin
  select * into v_job from public.scoring_jobs sj where sj.id=p_job_id for update;
  if not found or v_job.status not in ('dispatching','accepted','running') then return false; end if;
  update public.scoring_jobs set status='succeeded',result=p_result,finished_at=now(),updated_at=now(),error_code=null,error_message=null
    where id=p_job_id;
  if v_job.kind='entry' then
    update public.profiles p set entry_score=case when p_result ? 'qualification_score'
        then greatest(coalesce(p.entry_score,(p_result->>'qualification_score')::numeric),(p_result->>'qualification_score')::numeric)
        else p.entry_score end
      where p.id=v_job.user_id and p.status in ('new','active');
  elsif v_job.kind='submission' then
    insert into public.submissions(user_id,rnd,day,submitted_at,sha256,size_bytes,scoring_job_id)
      values(v_job.user_id,v_job.rnd,v_job.day,now(),v_job.sha256,v_job.size_bytes,v_job.id)
      on conflict(user_id,rnd,day) do update set submitted_at=excluded.submitted_at,sha256=excluded.sha256,
        size_bytes=excluded.size_bytes,scoring_job_id=excluded.scoring_job_id;
  end if;
  return true;
end $$;
revoke all on function public.complete_scoring_job(uuid,jsonb) from public,anon,authenticated;
grant execute on function public.complete_scoring_job(uuid,jsonb) to service_role;

create or replace function public.admin_close_qualification()
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_qualified int; v_registered int; v_cut numeric; v_groups int;
begin
  if auth.role()<>'service_role' and not public.is_admin() then raise exception 'admin_required' using errcode='42501'; end if;
  perform 1 from public.tournament_state ts where ts.id=1 for update;
  if (select ts.phase from public.tournament_state ts where ts.id=1)<>'entry' then raise exception 'entry_phase_required'; end if;
  if exists(select 1 from public.scoring_jobs sj where sj.kind='entry' and sj.status in ('dispatching','accepted','running')) then
    raise exception 'entry_jobs_still_running';
  end if;
  select rc.entry_cut,rc.num_groups into v_cut,v_groups from public.round_config rc where rc.rnd=1;
  if not found then raise exception 'round_one_not_configured'; end if;
  select count(*) into v_registered from public.profiles p where p.role='contestant';
  update public.profiles p set status='out',entry_score=null where p.role='contestant' and p.status<>'banned';
  update public.profiles p set entry_score=best.score,
    status=case when best.score>=v_cut then 'active'::public.user_status else 'out'::public.user_status end
  from (select sj.user_id,max((sj.result->>'qualification_score')::numeric) score
    from public.scoring_jobs sj where sj.kind='entry' and sj.status='succeeded'
      and sj.result ? 'qualification_score' group by sj.user_id) best
  where p.id=best.user_id and p.role='contestant' and p.status<>'banned';
  select count(*) into v_qualified from public.profiles p where p.role='contestant' and p.status='active';
  if v_qualified=0 then raise exception 'no_qualified_contestants'; end if;
  delete from public.round_members rm where rm.rnd=1;
  insert into public.round_members(rnd,user_id,grp,seed)
  with ordered as (select p.id,p.entry_score,row_number() over(order by p.entry_score desc,p.id) overall_rank
    from public.profiles p where p.role='contestant' and p.status='active'),
  banded as (select o.*,ceil(o.overall_rank::numeric/v_groups)::int band from ordered o),
  randomized as (select b.*,row_number() over(partition by b.band order by md5(b.id::text||':round-1'))-1 group_slot from banded b)
  select 1,r.id,(r.group_slot%v_groups)::int,r.overall_rank::int from randomized r;
  insert into public.contest_days(rnd,day,state) values(1,1,'open') on conflict(rnd,day) do update set state='open';
  update public.tournament_state set phase='round',current_round=1,current_day=1,pending_day=0,accepting_submissions=false,updated_at=now() where id=1;
  return jsonb_build_object('registered',v_registered,'qualified',v_qualified,'groups',v_groups,'entry_cut',v_cut);
end $$;
revoke all on function public.admin_close_qualification() from public,anon;
grant execute on function public.admin_close_qualification() to authenticated,service_role;
