-- Admin observability, official scoring URL, and round submission metadata.
alter table public.tournament_state
  add column if not exists scoring_module_url text;

create unique index if not exists scoring_jobs_one_round_submission
  on public.scoring_jobs(user_id, rnd, day)
  where kind = 'submission' and status in ('dispatching', 'accepted', 'running', 'succeeded');

create or replace function public.set_scoring_module_url(p_url text)
returns text language plpgsql security definer set search_path = public as $$
declare v_url text := nullif(btrim(p_url), '');
begin
  if not public.is_admin() then raise exception 'admin_required' using errcode = '42501'; end if;
  if v_url is not null and (
    length(v_url) > 2048 or
    v_url !~ '^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[^[:space:]?#]*)?$' and
    v_url !~ '^http://(localhost|127\.0\.0\.1)(:[0-9]{1,5})?(/[^[:space:]?#]*)?$'
  ) then
    raise exception 'invalid_scoring_url' using errcode = '22023';
  end if;
  update public.tournament_state set scoring_module_url = v_url, updated_at = now() where id = 1;
  return v_url;
end $$;
revoke all on function public.set_scoring_module_url(text) from public, anon;
grant execute on function public.set_scoring_module_url(text) to authenticated;

create or replace function public.set_tournament_context(
  p_phase public.tour_phase,
  p_round int,
  p_day int,
  p_accepting boolean,
  p_groups int default 1,
  p_top_n int default 0,
  p_wildcard_n int default 0,
  p_days int default 7,
  p_min_days int default 4,
  p_matches_per_day int default 7,
  p_is_offline boolean default false
)
returns public.tournament_state
language plpgsql security definer set search_path = public as $$
declare v_state public.tournament_state;
begin
  if not public.is_admin() then raise exception 'admin_required' using errcode = '42501'; end if;
  if p_phase = 'round' then
    if p_round < 1 or p_day < 1 or p_groups < 1 or p_top_n < 0 or p_wildcard_n < 0
       or p_days < 1 or p_min_days < 0 or p_min_days > p_days
       or p_matches_per_day < 1 then
      raise exception 'invalid_tournament_context' using errcode = '22023';
    end if;
    insert into public.round_config(rnd,num_groups,top_n,wildcard_n,days,min_days,matches_per_day,is_offline)
    values (p_round,p_groups,p_top_n,p_wildcard_n,p_days,p_min_days,p_matches_per_day,p_is_offline)
    on conflict (rnd) do update set num_groups=excluded.num_groups, top_n=excluded.top_n,
      wildcard_n=excluded.wildcard_n, days=excluded.days, min_days=excluded.min_days,
      matches_per_day=excluded.matches_per_day, is_offline=excluded.is_offline;
    if not exists (select 1 from public.round_members where rnd=p_round) then
      insert into public.round_members(rnd,user_id,grp,seed)
      select p_round, ranked.id, ((ranked.position - 1) % p_groups)::int, ranked.position::int
      from (select p.id, row_number() over(order by p.entry_score desc nulls last,p.created_at,p.id) position
            from public.profiles p where p.role='contestant' and p.status='active') ranked;
    end if;
    insert into public.contest_days(rnd,day,state)
      values(p_round,p_day,'open') on conflict(rnd,day) do update set state='open';
  else
    p_round := 0;
    p_day := 0;
  end if;
  update public.tournament_state set phase = p_phase,
    current_round = p_round, current_day = p_day,
    pending_day = case when p_phase = 'round' then 0 else pending_day end,
    accepting_submissions = case when p_phase = 'done' then false else p_accepting end,
    updated_at = now()
  where id = 1 returning * into v_state;
  return v_state;
end $$;
revoke all on function public.set_tournament_context(public.tour_phase,int,int,boolean,int,int,int,int,int,int,boolean) from public, anon;
grant execute on function public.set_tournament_context(public.tour_phase,int,int,boolean,int,int,int,int,int,int,boolean) to authenticated;

-- Keep the existing RPC contract while validating round/day state and enforcing
-- one accepted submission per contestant per round/day.
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
  if auth.uid() is null then raise exception 'authentication_required' using errcode = '28000'; end if;
  if p_kind not in ('entry', 'submission', 'test') then raise exception 'invalid_job_kind' using errcode = '22023'; end if;
  if p_size_bytes is null or p_size_bytes < 1 or p_size_bytes > 65536
     or p_sha256 is null or p_sha256 !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid_file_metadata' using errcode = '22023';
  end if;
  select * into v_profile from public.profiles where id = auth.uid() for update;
  if not found or v_profile.status = 'banned' then raise exception 'account_not_allowed' using errcode = '42501'; end if;
  select * into v_state from public.tournament_state where id = 1;
  if not found or not v_state.accepting_submissions or v_state.phase = 'done' then
    raise exception 'submissions_closed' using errcode = '55000';
  end if;
  if p_kind = 'entry' then
    if v_state.phase <> 'entry' then raise exception 'entry_closed' using errcode = '55000'; end if;
    select count(*) into v_attempts from public.scoring_jobs
      where user_id = auth.uid() and kind = 'entry' and status <> 'dispatch_failed';
    if v_attempts >= 20 then raise exception 'qualification_attempt_limit' using errcode = '54000'; end if;
  elsif p_kind = 'submission' then
    if v_state.phase <> 'round' or p_rnd is distinct from v_state.current_round
       or p_day is distinct from v_state.current_day then
      raise exception 'submission_context_stale' using errcode = '55000';
    end if;
    if v_profile.role <> 'admin' and (v_profile.status <> 'active'
       or not exists (select 1 from public.round_members rm where rm.rnd=p_rnd and rm.user_id=auth.uid())
       or exists (select 1 from public.round_config rc where rc.rnd=p_rnd and rc.is_offline)) then
      raise exception 'submission_not_allowed' using errcode = '42501';
    end if;
    if exists (select 1 from public.scoring_jobs j where j.user_id=auth.uid() and j.kind='submission'
       and j.rnd=p_rnd and j.day=p_day and j.status in ('dispatching','accepted','running','succeeded')) then
      raise exception 'already_submitted_today' using errcode = '23505';
    end if;
  elsif p_kind = 'test' then
    if p_rnd is not null or p_day is not null then raise exception 'invalid_test_context' using errcode = '22023'; end if;
  end if;
  insert into public.scoring_jobs(id,user_id,kind,rnd,day,sha256,size_bytes)
  values (p_job_id,auth.uid(),p_kind,case when p_kind='submission' then p_rnd end,
          case when p_kind='submission' then p_day end,p_sha256,p_size_bytes)
  returning * into v_job;
  return v_job;
exception when unique_violation then
  select * into v_job from public.scoring_jobs where id=p_job_id and user_id=auth.uid();
  if found then return v_job; end if;
  raise;
end $$;
revoke all on function public.create_scoring_job(uuid,text,int,int,text,int) from public, anon;
grant execute on function public.create_scoring_job(uuid,text,int,int,text,int) to authenticated;

create or replace function public.complete_scoring_job(p_job_id uuid, p_result jsonb)
returns boolean language plpgsql security definer set search_path = public as $$
declare v_job public.scoring_jobs; v_score numeric;
begin
  select * into v_job from public.scoring_jobs where id=p_job_id for update;
  if not found or v_job.status not in ('dispatching','accepted','running') then return false; end if;
  update public.scoring_jobs set status='succeeded',result=p_result,finished_at=now(),updated_at=now(),
    error_code=null,error_message=null where id=p_job_id;
  if v_job.kind='entry' then
    v_score := (p_result->>'converted_score')::numeric;
    if v_score is not null then update public.profiles set entry_score=v_score,
      status=case when coalesce((p_result->>'passed')::boolean,false) then 'active'::public.user_status else 'new'::public.user_status end
      where id=v_job.user_id and (entry_score is null or v_score>entry_score); end if;
  elsif v_job.kind='submission' then
    insert into public.submissions(user_id,rnd,day,submitted_at,sha256,size_bytes,scoring_job_id)
    values(v_job.user_id,v_job.rnd,v_job.day,now(),v_job.sha256,v_job.size_bytes,v_job.id)
    on conflict(user_id,rnd,day) do update set submitted_at=excluded.submitted_at,
      sha256=excluded.sha256,size_bytes=excluded.size_bytes,scoring_job_id=excluded.scoring_job_id;
  end if;
  return true;
end $$;
revoke all on function public.complete_scoring_job(uuid,jsonb) from public, anon, authenticated;
grant execute on function public.complete_scoring_job(uuid,jsonb) to service_role;

create or replace function public.get_my_dashboard()
returns jsonb language sql stable security definer set search_path = public as $$
  with me as (
    select p.*, au.email from public.profiles p join auth.users au on au.id=p.id where p.id=auth.uid()
  ), state as (select * from public.tournament_state where id=1),
  membership as (select rm.rnd,rm.grp from public.round_members rm join state s on s.current_round=rm.rnd where rm.user_id=auth.uid()),
  days as (select coalesce(jsonb_agg(jsonb_build_object('day',d.day,'pts',d.pts,'rank',d.rank,'n',d.group_size) order by d.day),'[]'::jsonb) value,
           avg(d.rank)::numeric(10,2) avg_rank from public.daily_results d join membership m on m.rnd=d.rnd and m.grp=d.grp where d.user_id=auth.uid()),
  board as (select coalesce(jsonb_agg(jsonb_build_object('rank',d.rank,'name',p.username,'pts',d.pts,'gs',d.gs) order by d.rank),'[]'::jsonb) value
            from public.daily_results d join membership m on m.rnd=d.rnd and m.grp=d.grp join public.profiles p on p.id=d.user_id
            where d.day=(select max(d2.day) from public.daily_results d2 where d2.rnd=d.rnd and d2.grp=d.grp)),
  attempts as (select count(*)::int value from public.scoring_jobs where user_id=auth.uid() and kind='entry' and status<>'dispatch_failed'),
  champion as (select p.username from state s left join public.profiles p on p.id=s.champion_id)
  select jsonb_build_object(
    'status',(select jsonb_build_object('name',me.username,'email',me.email,'role',me.role,'status',me.status,
      'phase',state.phase,'round',nullif(state.current_round,0),'open_day',nullif(state.current_day,0),
      'group',(select grp from membership limit 1),'entry',me.entry_score,'avg_rank',days.avg_rank,'days',days.value)
      from me cross join state cross join days),
    'scoring',(select jsonb_build_object('phase',state.phase,'accepting',state.accepting_submissions,
      'attempts',attempts.value,'bestScore',me.entry_score,'round',nullif(state.current_round,0),
      'day',nullif(state.current_day,0),'scoringUrl',state.scoring_module_url) from state cross join me cross join attempts),
    'standings',(select value from board),'champion',(select username from champion))
$$;
revoke all on function public.get_my_dashboard() from public, anon;
grant execute on function public.get_my_dashboard() to authenticated;

create or replace function public.get_admin_monitoring()
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare result jsonb;
begin
  if not public.is_admin() then raise exception 'admin_required' using errcode='42501'; end if;
  select jsonb_build_object(
    'state',(select to_jsonb(s) from public.tournament_state s where id=1),
    'profile_counts',(select jsonb_build_object('total',count(*) filter(where role='contestant'),
      'new',count(*) filter(where role='contestant' and status='new'),
      'active',count(*) filter(where role='contestant' and status='active'),
      'out',count(*) filter(where role='contestant' and status='out'),
      'banned',count(*) filter(where role='contestant' and status='banned')) from public.profiles),
    'job_counts',(select coalesce(jsonb_object_agg(status,n), '{}'::jsonb) from
      (select status,count(*) n from public.scoring_jobs group by status) q),
    'jobs',(select coalesce(jsonb_agg(to_jsonb(q) order by q.created_at desc),'[]'::jsonb) from (
      select j.id,j.user_id,p.username,j.kind,j.rnd,j.day,j.status,j.error_code,j.error_message,j.result,
        j.created_at,j.accepted_at,j.started_at,j.finished_at,j.updated_at
      from public.scoring_jobs j join public.profiles p on p.id=j.user_id order by j.created_at desc limit 200) q),
    'entrants',(select coalesce(jsonb_agg(to_jsonb(q) order by q.username),'[]'::jsonb) from (
      select p.id,p.username,p.status,p.entry_score,p.created_at,rm.grp,
        exists(select 1 from public.submissions s join public.tournament_state ts on ts.id=1
          where s.user_id=p.id and s.rnd=ts.current_round and s.day=ts.current_day) submitted,
        (select count(*)::int from public.scoring_jobs j where j.user_id=p.id and j.kind='entry' and j.status<>'dispatch_failed') entry_attempts,
        (select max(j.created_at) from public.scoring_jobs j where j.user_id=p.id) last_activity
      from public.profiles p left join public.round_members rm on rm.user_id=p.id
        and rm.rnd=(select current_round from public.tournament_state where id=1)
      where p.role='contestant' limit 4000) q),
    'days',(select coalesce(jsonb_agg(to_jsonb(d) order by d.rnd desc,d.day desc),'[]'::jsonb)
      from (select * from public.contest_days order by rnd desc,day desc limit 100) d),
    'matches',(select coalesce(jsonb_agg(to_jsonb(q) order by q.rnd desc,q.day desc,q.id desc),'[]'::jsonb) from (
      select m.id,m.rnd,m.day,m.grp,m.rd,m.state,m.score_a,m.points_a,m.points_b,m.finished_at,m.has_replay,pa.username player_a,pb.username player_b
      from public.matches m join public.profiles pa on pa.id=m.player_a join public.profiles pb on pb.id=m.player_b
      order by m.id desc limit 200) q),
    'daily_results',(select coalesce(jsonb_agg(to_jsonb(q) order by q.rnd desc,q.day desc,q.grp,q.rank),'[]'::jsonb) from (
      select d.rnd,d.day,d.grp,d.user_id,p.username,d.pts,d.gs,d.rank,d.group_size
      from public.daily_results d join public.profiles p on p.id=d.user_id
      order by d.rnd desc,d.day desc,d.grp,d.rank limit 500) q),
    'round_config',(select coalesce(jsonb_agg(to_jsonb(rc) order by rnd),'[]'::jsonb) from public.round_config rc),
    'replay_storage',(select jsonb_build_object('objects',count(*),'bytes',coalesce(sum(size_bytes),0),
      'failed',count(*) filter(where state<>'ready')) from public.replay_objects)
  ) into result;
  return result;
end $$;
revoke all on function public.get_admin_monitoring() from public, anon;
grant execute on function public.get_admin_monitoring() to authenticated;
