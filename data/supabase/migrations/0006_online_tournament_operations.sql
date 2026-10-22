-- Online tournament operations. Match pairing, standings and advancement stay in Postgres.

alter table public.round_config
  add column if not exists entry_cut numeric not null default -2;
alter table public.tournament_state
  add column if not exists max_contestants int not null default 4000;
alter table public.contest_days
  add column if not exists publish_after timestamptz;
alter table public.matches alter column score_a drop not null;
alter table public.matches
  add column if not exists state text not null default 'pending'
    check (state in ('pending','running','completed','forfeit')),
  add column if not exists points_a int,
  add column if not exists points_b int,
  add column if not exists started_at timestamptz,
  add column if not exists finished_at timestamptz;
update public.matches set state='completed',points_a=sign(score_a),points_b=-sign(score_a)
  where score_a is not null and state='pending';

create table if not exists public.round_byes (
  rnd int not null,
  day int not null,
  rd int not null,
  grp int not null,
  user_id uuid not null references public.profiles(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (rnd, day, rd, grp)
);
alter table public.round_byes enable row level security;
drop policy if exists round_byes_admin_read on public.round_byes;
create policy round_byes_admin_read on public.round_byes for select to authenticated using (public.is_admin());
revoke all on public.round_byes from anon, authenticated;
grant select on public.round_byes to authenticated;

-- Capacity check is serialized so simultaneous account creation cannot exceed 4,000.
create or replace function public.enforce_tournament_capacity()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if new.role = 'contestant' then
    perform pg_advisory_xact_lock(7740021);
    if (select count(*) from public.profiles where role='contestant') >= coalesce(
      (select max_contestants from public.tournament_state where id=1),4000
    ) then
      raise exception 'contestant_capacity_reached' using errcode='54000';
    end if;
  end if;
  return new;
end $$;
drop trigger if exists profiles_capacity_guard on public.profiles;
create trigger profiles_capacity_guard before insert on public.profiles
for each row execute function public.enforce_tournament_capacity();

-- Define the five week formats. Week five is offline and intentionally not operable by this online service.
insert into public.round_config(rnd,num_groups,top_n,wildcard_n,days,min_days,matches_per_day,is_offline)
values (1,40,10,40,7,4,7,false),(2,16,8,16,7,4,7,false),(3,8,6,8,7,4,7,false),
       (4,4,4,4,7,4,7,false),(5,1,1,0,7,4,7,true)
on conflict (rnd) do update set num_groups=excluded.num_groups,top_n=excluded.top_n,
  wildcard_n=excluded.wildcard_n,days=excluded.days,min_days=excluded.min_days,
  matches_per_day=excluded.matches_per_day,is_offline=excluded.is_offline;

-- Store the best weighted qualification score, not the presentation score out of 100.
create or replace function public.complete_scoring_job(p_job_id uuid, p_result jsonb)
returns boolean language plpgsql security definer set search_path = public as $$
declare v_job public.scoring_jobs; v_score numeric;
begin
  select * into v_job from public.scoring_jobs where id=p_job_id for update;
  if not found or v_job.status not in ('dispatching','accepted','running') then return false; end if;
  update public.scoring_jobs set status='succeeded',result=p_result,finished_at=now(),updated_at=now(),
    error_code=null,error_message=null where id=p_job_id;
  if v_job.kind='entry' then
    v_score := (p_result->>'qualification_score')::numeric;
    if v_score is not null then
      update public.profiles p set entry_score=v_score,
        status=case when v_score >= -2 then 'active'::public.user_status else 'out'::public.user_status end
      where p.id=v_job.user_id and (p.entry_score is null or v_score>p.entry_score);
    end if;
  elsif v_job.kind='submission' then
    insert into public.submissions(user_id,rnd,day,submitted_at,sha256,size_bytes,scoring_job_id)
    values(v_job.user_id,v_job.rnd,v_job.day,now(),v_job.sha256,v_job.size_bytes,v_job.id)
    on conflict(user_id,rnd,day) do update set submitted_at=excluded.submitted_at,
      sha256=excluded.sha256,size_bytes=excluded.size_bytes,scoring_job_id=excluded.scoring_job_id;
  end if;
  return true;
end $$;
revoke all on function public.complete_scoring_job(uuid,jsonb) from public,anon,authenticated;
grant execute on function public.complete_scoring_job(uuid,jsonb) to service_role;

create or replace function public.admin_close_qualification()
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_qualified int; v_registered int;
begin
  if auth.role()<>'service_role' and not public.is_admin() then raise exception 'admin_required' using errcode='42501'; end if;
  perform 1 from public.tournament_state where id=1 for update;
  if (select phase from public.tournament_state where id=1)<>'entry' then raise exception 'entry_phase_required'; end if;
  if exists(select 1 from public.scoring_jobs where kind='entry' and status in ('dispatching','accepted','running')) then
    raise exception 'entry_jobs_still_running';
  end if;
  select count(*) into v_registered from public.profiles where role='contestant';
  update public.profiles set status='out',entry_score=null where role='contestant';
  update public.profiles p set entry_score=best.score,
    status=case when best.score >= -2 then 'active'::public.user_status else 'out'::public.user_status end
  from (
    select user_id,max((result->>'qualification_score')::numeric) score
    from public.scoring_jobs where kind='entry' and status='succeeded'
      and result ? 'qualification_score' group by user_id
  ) best where p.id=best.user_id and p.role='contestant';
  update public.profiles set status='out' where role='contestant' and status='new';
  select count(*) into v_qualified from public.profiles where role='contestant' and status='active';
  if v_qualified=0 then raise exception 'no_qualified_contestants'; end if;
  delete from public.round_members where rnd=1;
  insert into public.round_members(rnd,user_id,grp,seed)
  with ordered as (
    select id,entry_score,row_number() over(order by entry_score desc,id) overall_rank
    from public.profiles where role='contestant' and status='active'
  ), banded as (
    select *,ceil(overall_rank/40.0)::int band from ordered
  ), randomized as (
    select *,row_number() over(partition by band order by md5(id::text||':round-1'))-1 group_slot from banded
  ) select 1,id,(group_slot % 40)::int,overall_rank::int from randomized;
  insert into public.contest_days(rnd,day,state) values(1,1,'open') on conflict(rnd,day) do update set state='open';
  update public.tournament_state set phase='round',current_round=1,current_day=1,pending_day=0,
    accepting_submissions=true,updated_at=now() where id=1;
  return jsonb_build_object('registered',v_registered,'qualified',v_qualified,'groups',40);
end $$;
revoke all on function public.admin_close_qualification() from public,anon;
grant execute on function public.admin_close_qualification() to authenticated,service_role;

create or replace function public.admin_open_tournament_day(p_rnd int,p_day int)
returns boolean language plpgsql security definer set search_path = public as $$
declare v_state public.tournament_state; v_config public.round_config;
begin
  if auth.role()<>'service_role' and not public.is_admin() then raise exception 'admin_required' using errcode='42501'; end if;
  select * into v_state from public.tournament_state where id=1 for update;
  select * into v_config from public.round_config where rnd=p_rnd;
  if not found or v_config.is_offline then raise exception 'online_round_not_configured'; end if;
  if v_state.phase<>'round' or v_state.current_round<>p_rnd then raise exception 'round_context_stale'; end if;
  if p_day<1 or p_day>v_config.days then raise exception 'invalid_day'; end if;
  if p_day>1 and not exists(select 1 from public.contest_days where rnd=p_rnd and day=p_day-1 and state='graded') then
    raise exception 'previous_day_not_graded';
  end if;
  insert into public.contest_days(rnd,day,state) values(p_rnd,p_day,'open') on conflict(rnd,day) do update set state='open';
  update public.tournament_state set current_day=p_day,pending_day=0,accepting_submissions=true,updated_at=now() where id=1;
  return true;
end $$;
revoke all on function public.admin_open_tournament_day(int,int) from public,anon;
grant execute on function public.admin_open_tournament_day(int,int) to authenticated,service_role;

create or replace function public.admin_close_tournament_day()
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_state public.tournament_state;
begin
  if auth.role()<>'service_role' and not public.is_admin() then raise exception 'admin_required' using errcode='42501'; end if;
  select * into v_state from public.tournament_state where id=1 for update;
  if v_state.phase<>'round' or v_state.current_round<1 or v_state.current_day<1 then raise exception 'round_context_required'; end if;
  if exists(select 1 from public.scoring_jobs where kind='submission' and rnd=v_state.current_round and day=v_state.current_day
    and status in ('dispatching','accepted','running')) then raise exception 'submission_jobs_still_running'; end if;
  update public.contest_days set state='grading',closed_at=coalesce(closed_at,now())
    where rnd=v_state.current_round and day=v_state.current_day and state in ('open','closed');
  if not found then raise exception 'day_not_open'; end if;
  update public.tournament_state set accepting_submissions=false,pending_day=v_state.current_day,updated_at=now() where id=1;
  return jsonb_build_object('round',v_state.current_round,'day',v_state.current_day,'state','grading');
end $$;
revoke all on function public.admin_close_tournament_day() from public,anon;
grant execute on function public.admin_close_tournament_day() to authenticated,service_role;

-- Match generation is transactional and lives in Postgres. Rd 1 seeds top-half vs bottom-half;
-- rds 2-7 greedily pair equal points while avoiding prior opponents where possible.
create or replace function public.prepare_swiss_round(p_rnd int,p_day int,p_rd int)
returns table(match_id bigint,grp int,player_a uuid,player_b uuid,job_a uuid,job_b uuid,match_state text)
language plpgsql security definer set search_path = public as $$
declare g record; v_order uuid[]; v_n int; v_half int; v_a uuid; v_b uuid; v_i int; v_j int;
begin
  if auth.role()<>'service_role' and not public.is_admin() then raise exception 'admin_required' using errcode='42501'; end if;
  if p_rd<1 or p_rd>7 then raise exception 'invalid_match_round'; end if;
  if not exists(select 1 from public.contest_days where rnd=p_rnd and day=p_day and state in ('open','grading')) then raise exception 'day_not_open'; end if;
  if p_rd>1 and exists(select 1 from public.matches where rnd=p_rnd and day=p_day and rd=p_rd-1 and state not in ('completed','forfeit')) then
    raise exception 'previous_match_round_pending';
  end if;
  for g in select distinct rm.grp from public.round_members rm where rm.rnd=p_rnd order by rm.grp loop
    if p_rd=1 then
      select array_agg(q.user_id order by q.avg_rank,q.seed,q.user_id) into v_order from (
        select rm.user_id,rm.seed,coalesce((select avg(dr.rank) from public.daily_results dr
          where dr.rnd=rm.rnd and dr.user_id=rm.user_id and dr.day<p_day),0) avg_rank
        from public.round_members rm where rm.rnd=p_rnd and rm.grp=g.grp and (
          p_day<>7 or (select count(*) from public.submissions s where s.user_id=rm.user_id and s.rnd=p_rnd and s.day between 1 and 6)>=4
        )
      ) q;
    else
      select array_agg(q.user_id order by q.points desc,q.avg_rank,q.seed,q.user_id) into v_order from (
        select rm.user_id,rm.seed,coalesce((select avg(dr.rank) from public.daily_results dr
            where dr.rnd=rm.rnd and dr.user_id=rm.user_id and dr.day<p_day),0) avg_rank,
          coalesce((select sum(case when m.player_a=rm.user_id then m.points_a else m.points_b end)
            from public.matches m where m.rnd=p_rnd and m.day=p_day and m.rd<p_rd
              and m.state in ('completed','forfeit') and (m.player_a=rm.user_id or m.player_b=rm.user_id)),0) points
        from public.round_members rm
        where rm.rnd=p_rnd and rm.grp=g.grp and (
          p_day<>7 or (select count(*) from public.submissions s where s.user_id=rm.user_id and s.rnd=p_rnd and s.day between 1 and 6)>=4
        )
      ) q;
    end if;
    v_n:=coalesce(array_length(v_order,1),0);
    if v_n=0 then continue; end if;
    if v_n%2=1 then
      v_a:=null;
      for v_i in reverse v_n..1 loop
        if not exists(select 1 from public.round_byes b where b.rnd=p_rnd and b.grp=g.grp and b.user_id=v_order[v_i]) then
          v_a:=v_order[v_i]; exit;
        end if;
      end loop;
      if v_a is null then v_a:=v_order[v_n]; end if;
      insert into public.round_byes(rnd,day,rd,grp,user_id) values(p_rnd,p_day,p_rd,g.grp,v_a) on conflict do nothing;
      v_order:=array_remove(v_order,v_a); v_n:=array_length(v_order,1);
    end if;
    v_half:=v_n/2;
    if p_rd=1 then
      for v_i in 1..v_half loop
        v_a:=v_order[v_i]; v_b:=v_order[v_i+v_half];
        insert into public.matches(rnd,day,rd,grp,player_a,player_b,state)
        values(p_rnd,p_day,p_rd,g.grp,v_a,v_b,'pending') on conflict(rnd,day,rd,player_a,player_b) do nothing;
      end loop;
    else
      while coalesce(array_length(v_order,1),0)>=2 loop
        v_a:=v_order[1]; v_b:=null;
        for v_j in 2..array_length(v_order,1) loop
          if not exists(select 1 from public.matches old where old.rnd=p_rnd and old.grp=g.grp and old.day=p_day
            and ((old.player_a=v_a and old.player_b=v_order[v_j]) or (old.player_a=v_order[v_j] and old.player_b=v_a))) then
            v_b:=v_order[v_j]; exit;
          end if;
        end loop;
        if v_b is null then v_b:=v_order[2]; end if;
        insert into public.matches(rnd,day,rd,grp,player_a,player_b,state)
        values(p_rnd,p_day,p_rd,g.grp,v_a,v_b,'pending') on conflict(rnd,day,rd,player_a,player_b) do nothing;
        v_order:=array_remove(array_remove(v_order,v_a),v_b);
      end loop;
    end if;
  end loop;
  return query select m.id,m.grp,m.player_a,m.player_b,sa.scoring_job_id,sb.scoring_job_id,m.state
    from public.matches m
    left join public.submissions sa on sa.user_id=m.player_a and sa.rnd=m.rnd and sa.day=m.day
    left join public.submissions sb on sb.user_id=m.player_b and sb.rnd=m.rnd and sb.day=m.day
    where m.rnd=p_rnd and m.day=p_day and m.rd=p_rd order by m.grp,m.id;
end $$;
revoke all on function public.prepare_swiss_round(int,int,int) from public,anon;
grant execute on function public.prepare_swiss_round(int,int,int) to authenticated,service_role;

create or replace function public.record_tournament_match(p_match_id bigint,p_score_a int,p_a_ready boolean,p_b_ready boolean)
returns boolean language plpgsql security definer set search_path = public as $$
declare m public.matches;
begin
  if auth.role()<>'service_role' and not public.is_admin() then raise exception 'admin_required' using errcode='42501'; end if;
  select * into m from public.matches where id=p_match_id for update;
  if not found or m.state not in ('pending','running') then return false; end if;
  if (not p_a_ready or not p_b_ready) and not exists(select 1 from public.contest_days cd where cd.rnd=m.rnd and cd.day=m.day and cd.state='grading') then
    raise exception 'day_not_closed_forfeit';
  end if;
  if p_a_ready and p_b_ready then
    if p_score_a is null or p_score_a not between -2 and 2 then raise exception 'invalid_match_score'; end if;
    update public.matches set score_a=p_score_a,points_a=sign(p_score_a),points_b=-sign(p_score_a),state='completed',finished_at=now()
      where id=p_match_id;
  else
    update public.matches set score_a=0,points_a=case when p_a_ready then 1 else -1 end,
      points_b=case when p_b_ready then 1 else -1 end,state='forfeit',finished_at=now()
      where id=p_match_id;
  end if;
  return true;
end $$;
revoke all on function public.record_tournament_match(bigint,int,boolean,boolean) from public,anon,authenticated;
grant execute on function public.record_tournament_match(bigint,int,boolean,boolean) to service_role;

create or replace function public.mark_tournament_match_running(p_match_id bigint)
returns boolean language plpgsql security definer set search_path=public as $$
begin
  if auth.role()<>'service_role' then raise exception 'service_role_required' using errcode='42501'; end if;
  update public.matches set state='running',started_at=now()
    where id=p_match_id and (state='pending' or (state='running' and started_at < now()-interval '2 minutes'));
  return found;
end $$;
revoke all on function public.mark_tournament_match_running(bigint) from public,anon,authenticated;
grant execute on function public.mark_tournament_match_running(bigint) to service_role;

create or replace function public.finalize_tournament_day(p_rnd int,p_day int)
returns jsonb language plpgsql security definer set search_path = public as $$
declare cfg public.round_config; v_next int; v_survivors int:=0;
begin
  if auth.role()<>'service_role' and not public.is_admin() then raise exception 'admin_required' using errcode='42501'; end if;
  select * into cfg from public.round_config where rnd=p_rnd;
  if not found or p_day<1 or p_day>cfg.days then raise exception 'invalid_day'; end if;
  if exists(select 1 from public.matches where rnd=p_rnd and day=p_day and state not in ('completed','forfeit')) then raise exception 'matches_pending'; end if;
  delete from public.daily_results where rnd=p_rnd and day=p_day;
  insert into public.daily_results(rnd,day,user_id,grp,pts,gs,rank,group_size)
  with scores as (
    select player_a user_id,grp,points_a pts,coalesce(score_a,0) gs from public.matches where rnd=p_rnd and day=p_day and state in ('completed','forfeit')
    union all
    select player_b,grp,points_b,-coalesce(score_a,0) from public.matches where rnd=p_rnd and day=p_day and state in ('completed','forfeit')
    union all
    select user_id,grp,0,0 from public.round_byes where rnd=p_rnd and day=p_day
  ), totals as (select user_id,grp,sum(pts)::int pts,sum(gs)::int gs from scores group by user_id,grp), ranked as (
    select t.*,count(*) over(partition by grp)::int n,
      row_number() over(partition by grp order by pts desc,gs desc,rm.seed,rm.user_id)::int r
    from totals t join public.round_members rm on rm.rnd=p_rnd and rm.user_id=t.user_id
  ) select p_rnd,p_day,user_id,grp,pts,gs,r,n from ranked;
  update public.contest_days set state='graded',graded_at=now(),
    publish_after=(date_trunc('day',now() at time zone 'Asia/Ho_Chi_Minh')+interval '1 day') at time zone 'Asia/Ho_Chi_Minh',
    total_matches=(select count(*) from public.matches where rnd=p_rnd and day=p_day) where rnd=p_rnd and day=p_day;
  if p_day=cfg.days then
    insert into public.round_advancement(rnd,user_id,route,avg_rank_pct,final_rank)
    with cfg as (select top_n,wildcard_n from public.round_config where rnd=p_rnd),
    final_day as (select * from public.daily_results where rnd=p_rnd and day=p_day),
    history as (select d.user_id,avg((d.rank-1)::numeric/nullif(d.group_size,0)) pct
      from public.daily_results d where d.rnd=p_rnd and d.day<p_day group by d.user_id),
    wildcard_order as (select f.user_id,row_number() over(order by h.pct nulls last,f.user_id) n
      from final_day f cross join cfg left join history h on h.user_id=f.user_id where f.rank>cfg.top_n),
    decision as (
      select rm.user_id,coalesce(h.pct,1) pct,f.rank,
        case when f.user_id is null then 'ineligible'::public.advance_route
          when f.rank<=cfg.top_n then 'top'::public.advance_route
          when wo.n<=cfg.wildcard_n then 'wildcard'::public.advance_route
          else 'eliminated'::public.advance_route end route
      from public.round_members rm cross join cfg
      left join final_day f on f.user_id=rm.user_id
      left join history h on h.user_id=rm.user_id
      left join wildcard_order wo on wo.user_id=rm.user_id
      where rm.rnd=p_rnd
    )
    select p_rnd,user_id,route,pct,rank from decision
    on conflict(rnd,user_id) do update set route=excluded.route,avg_rank_pct=excluded.avg_rank_pct,final_rank=excluded.final_rank;
    update public.profiles p set status=case when a.route in ('top','wildcard') then 'active'::public.user_status else 'out'::public.user_status end
      from public.round_advancement a where a.rnd=p_rnd and a.user_id=p.id;
    select count(*) into v_survivors from public.round_advancement where rnd=p_rnd and route in ('top','wildcard');
    v_next:=p_rnd+1;
    if v_next<=4 then
      insert into public.round_members(rnd,user_id,grp,seed)
      with ordered as (select p.id,p.entry_score,a.avg_rank_pct,row_number() over(order by a.avg_rank_pct,p.entry_score desc,p.id) pos
        from public.round_advancement a join public.profiles p on p.id=a.user_id where a.rnd=p_rnd and a.route in ('top','wildcard')),
      banded as (select *,ceil(pos::numeric/(select num_groups from public.round_config where rnd=v_next))::int band from ordered),
      placed as (select *,row_number() over(partition by band order by md5(id::text||':'||v_next::text))-1 slot from banded)
      select v_next,id,(slot%(select num_groups from public.round_config where rnd=v_next))::int,pos::int from placed;
      insert into public.contest_days(rnd,day,state) values(v_next,1,'open') on conflict(rnd,day) do update set state='open';
      update public.tournament_state set current_round=v_next,current_day=1,pending_day=0,phase='round',accepting_submissions=true,updated_at=now() where id=1;
    else
      update public.tournament_state set phase='done',accepting_submissions=false,pending_day=0,updated_at=now() where id=1;
    end if;
  end if;
  return jsonb_build_object('round',p_rnd,'day',p_day,'survivors',v_survivors,'next_round',case when p_day=cfg.days and p_rnd<4 then p_rnd+1 else null end);
end $$;
revoke all on function public.finalize_tournament_day(int,int) from public,anon;
grant execute on function public.finalize_tournament_day(int,int) to authenticated,service_role;

create or replace function public.admin_publish_tournament_day(p_rnd int,p_day int)
returns boolean language plpgsql security definer set search_path=public as $$
begin
  if not public.is_admin() then raise exception 'admin_required' using errcode='42501'; end if;
  update public.contest_days set publish_after=now(),graded_at=coalesce(graded_at,now())
   where rnd=p_rnd and day=p_day and state='graded';
  return found;
end $$;
revoke all on function public.admin_publish_tournament_day(int,int) from public,anon;
grant execute on function public.admin_publish_tournament_day(int,int) to authenticated;

-- Admin-only live table for operations/Google Sheets. Contestant RPCs remain delayed.
create or replace function public.get_admin_live_standings()
returns jsonb language plpgsql stable security definer set search_path=public as $$
declare result jsonb; v_rnd int; v_day int;
begin
  if not public.is_admin() then raise exception 'admin_required' using errcode='42501'; end if;
  select current_round,current_day into v_rnd,v_day from public.tournament_state where id=1;
  select coalesce(jsonb_agg(to_jsonb(q) order by q.grp,q.rank),'[]'::jsonb) into result
  from (
    with totals as (
      select rm.user_id,rm.grp,rm.seed,coalesce(sum(case
        when m.player_a=rm.user_id then m.points_a else m.points_b end),0)::int pts,
        coalesce(sum(case when m.player_a=rm.user_id then m.score_a else -m.score_a end),0)::int gs,
        count(m.id) filter(where m.state in ('completed','forfeit'))::int completed_matches
      from public.round_members rm
      left join public.matches m on m.rnd=rm.rnd and m.day=v_day and m.grp=rm.grp
        and m.state in ('completed','forfeit') and (m.player_a=rm.user_id or m.player_b=rm.user_id)
      where rm.rnd=v_rnd group by rm.user_id,rm.grp,rm.seed
    ), ranked as (
      select t.*,row_number() over(partition by t.grp order by t.pts desc,t.gs desc,t.seed,t.user_id)::int rank,
        count(*) over(partition by t.grp)::int group_size
      from totals t
    )
    select r.grp,r.rank,r.group_size,p.id user_id,p.username,r.pts,r.gs,r.completed_matches,
      coalesce((select count(*) from public.scoring_jobs j where j.user_id=p.id and j.kind='submission'
        and j.rnd=v_rnd and j.day=v_day and j.status='succeeded'),0)::int submitted,
      (select count(*) from public.matches m where m.rnd=v_rnd and m.day=v_day and m.grp=r.grp
        and m.state in ('completed','forfeit'))::int group_completed_matches,
      (select count(*) from public.matches m where m.rnd=v_rnd and m.day=v_day and m.grp=r.grp)::int group_total_matches
    from ranked r join public.profiles p on p.id=r.user_id
  ) q;
  return jsonb_build_object('round',v_rnd,'day',v_day,'standings',result);
end $$;
revoke all on function public.get_admin_live_standings() from public,anon;
grant execute on function public.get_admin_live_standings() to authenticated;

create or replace function public.get_group_leaderboard(p_rnd int,p_day int default null)
returns table(rank int,username text,pts int,gs int,group_size int,day int)
language sql stable security definer set search_path=public as $$
  select d.rank,p.username,d.pts,d.gs,d.group_size,d.day
  from public.round_members me join public.daily_results d on d.rnd=me.rnd and d.grp=me.grp
  join public.profiles p on p.id=d.user_id
  join public.contest_days cd on cd.rnd=d.rnd and cd.day=d.day and cd.state='graded' and cd.publish_after<=now()
  where me.user_id=auth.uid() and me.rnd=p_rnd
    and d.day=coalesce(p_day,(select max(x.day) from public.daily_results x join public.contest_days cdx
      on cdx.rnd=x.rnd and cdx.day=x.day and cdx.state='graded' and cdx.publish_after<=now()
      where x.rnd=me.rnd and x.grp=me.grp))
  order by d.rank;
$$;
revoke all on function public.get_group_leaderboard(int,int) from public,anon;
grant execute on function public.get_group_leaderboard(int,int) to authenticated;

create or replace function public.get_group_matches(p_rnd int,p_day int)
returns table(match_id bigint,rd int,player_a text,player_b text,score_a smallint,has_replay boolean)
language sql stable security definer set search_path=public as $$
  select m.id,m.rd,pa.username,pb.username,m.score_a,m.has_replay
  from public.round_members me join public.matches m on m.rnd=me.rnd and m.grp=me.grp
  join public.profiles pa on pa.id=m.player_a join public.profiles pb on pb.id=m.player_b
  join public.contest_days cd on cd.rnd=m.rnd and cd.day=m.day and cd.state='graded' and cd.publish_after<=now()
  where me.user_id=auth.uid() and me.rnd=p_rnd and m.day=p_day order by m.rd,m.id;
$$;
revoke all on function public.get_group_matches(int,int) from public,anon;
grant execute on function public.get_group_matches(int,int) to authenticated;

-- No direct mid-day score or source visibility for contestants.
drop policy if exists daily_self_read on public.daily_results;
create policy daily_self_read on public.daily_results for select to authenticated using (
  public.is_admin() or (user_id=auth.uid() and exists(select 1 from public.contest_days cd
    where cd.rnd=daily_results.rnd and cd.day=daily_results.day and cd.state='graded' and cd.publish_after<=now()))
);
drop policy if exists matches_self_read on public.matches;
create policy matches_self_read on public.matches for select to authenticated using (
  public.is_admin() or ((player_a=auth.uid() or player_b=auth.uid()) and exists(select 1 from public.contest_days cd
    where cd.rnd=matches.rnd and cd.day=matches.day and cd.state='graded' and cd.publish_after<=now()))
);

create or replace function public.get_my_today_matches()
returns table(rnd int,day int,rd int,grp int,opponent text,state text)
language sql stable security definer set search_path=public as $$
  select m.rnd,m.day,m.rd,m.grp,
    case when m.player_a=auth.uid() then pb.username else pa.username end opponent,
    m.state
  from public.matches m join public.profiles pa on pa.id=m.player_a join public.profiles pb on pb.id=m.player_b
  join public.tournament_state ts on ts.current_round=m.rnd and ts.current_day=m.day and ts.phase='round'
  where m.player_a=auth.uid() or m.player_b=auth.uid()
  order by m.rd;
$$;
revoke all on function public.get_my_today_matches() from public,anon;
grant execute on function public.get_my_today_matches() to authenticated;

create or replace function public.get_my_dashboard()
returns jsonb language sql stable security definer set search_path=public as $$
  with me as (select p.*,au.email from public.profiles p join auth.users au on au.id=p.id where p.id=auth.uid()),
  state as (select * from public.tournament_state where id=1),
  membership as (select rm.rnd,rm.grp from public.round_members rm join state s on s.current_round=rm.rnd where rm.user_id=auth.uid()),
  days as (select coalesce(jsonb_agg(jsonb_build_object('day',d.day,'pts',d.pts,'rank',d.rank,'n',d.group_size) order by d.day),'[]'::jsonb) value,
    avg(d.rank)::numeric(10,2) avg_rank from public.daily_results d join membership m on m.rnd=d.rnd and m.grp=d.grp
    join public.contest_days cd on cd.rnd=d.rnd and cd.day=d.day and cd.state='graded' and cd.publish_after<=now() where d.user_id=auth.uid()),
  board as (select coalesce(jsonb_agg(jsonb_build_object('rank',d.rank,'name',p.username,'pts',d.pts,'gs',d.gs) order by d.rank),'[]'::jsonb) value
    from public.daily_results d join membership m on m.rnd=d.rnd and m.grp=d.grp join public.profiles p on p.id=d.user_id
    join public.contest_days cd on cd.rnd=d.rnd and cd.day=d.day and cd.state='graded' and cd.publish_after<=now()
    where d.day=(select max(d2.day) from public.daily_results d2 join public.contest_days cd2
      on cd2.rnd=d2.rnd and cd2.day=d2.day and cd2.state='graded' and cd2.publish_after<=now() where d2.rnd=d.rnd and d2.grp=d.grp)),
  attempts as (select count(*)::int value from public.scoring_jobs where user_id=auth.uid() and kind='entry' and status<>'dispatch_failed'),
  champion as (select p.username from state s left join public.profiles p on p.id=s.champion_id)
  select jsonb_build_object(
    'status',(select jsonb_build_object('name',me.username,'email',me.email,'role',me.role,'status',me.status,'phase',state.phase,
      'round',nullif(state.current_round,0),'open_day',nullif(state.current_day,0),'group',(select grp from membership limit 1),
      'entry',me.entry_score,'avg_rank',days.avg_rank,'days',days.value) from me cross join state cross join days),
    'scoring',(select jsonb_build_object('phase',state.phase,'accepting',state.accepting_submissions,'attempts',attempts.value,
      'bestScore',me.entry_score,'round',nullif(state.current_round,0),'day',nullif(state.current_day,0),
      'scoringUrl',state.scoring_module_url) from state cross join me cross join attempts),
    'standings',(select value from board),'champion',(select username from champion))
$$;
revoke all on function public.get_my_dashboard() from public,anon;
grant execute on function public.get_my_dashboard() to authenticated;
