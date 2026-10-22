-- Fix ambiguous output column references in scoring/admin RPCs and expose a
-- manual submission gate that does not advance the tournament workflow.

create or replace function public.admin_list_eliminated_contestants()
returns table(id uuid, username text, email text, status public.user_status,
              entry_score numeric, created_at timestamptz, grp int)
language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
  end if;
  return query
    select p.id, p.username, au.email::text, p.status, p.entry_score, p.created_at,
           rm.grp
    from public.profiles p
    join auth.users au on au.id = p.id
    left join public.round_members rm
      on rm.user_id = p.id
     and rm.rnd = (select ts.current_round from public.tournament_state ts where ts.id = 1)
    where p.role = 'contestant' and p.status in ('out', 'banned')
    order by case when p.status = 'banned' then 0 else 1 end,
             p.username;
end $$;
revoke all on function public.admin_list_eliminated_contestants() from public, anon;
grant execute on function public.admin_list_eliminated_contestants() to authenticated;

create or replace function public.finalize_tournament_day(p_rnd int,p_day int)
returns jsonb language plpgsql security definer set search_path = public as $$
declare cfg public.round_config; v_state public.tournament_state; v_day_state public.day_state; v_next int; v_survivors int:=0;
begin
  if auth.role()<>'service_role' and not public.is_admin() then raise exception 'admin_required' using errcode='42501'; end if;
  select * into v_state from public.tournament_state where id=1 for update;
  if not found then raise exception 'tournament_state_missing'; end if;
  select cd.state into v_day_state from public.contest_days cd where cd.rnd=p_rnd and cd.day=p_day;
  select rc.* into cfg from public.round_config rc where rc.rnd=p_rnd;
  if not found or p_day<1 or p_day>cfg.days then raise exception 'invalid_day'; end if;
  if v_day_state='graded' then
    return jsonb_build_object('round',p_rnd,'day',p_day,'survivors',
      (select count(*) from public.round_advancement ra where ra.rnd=p_rnd and ra.route in ('top','wildcard')),
      'next_round',case when p_day=cfg.days and p_rnd<4 then p_rnd+1 else null end,
      'already_finalized',true);
  end if;
  if v_state.phase<>'round' or v_state.current_round<>p_rnd or v_state.current_day<>p_day then
    raise exception 'round_context_stale' using errcode='55000';
  end if;
  if v_day_state is distinct from 'grading' then raise exception 'day_not_closed'; end if;
  if exists(select 1 from public.matches m where m.rnd=p_rnd and m.day=p_day and m.state not in ('completed','forfeit')) then raise exception 'matches_pending'; end if;
  delete from public.daily_results dr where dr.rnd=p_rnd and dr.day=p_day;
  insert into public.daily_results(rnd,day,user_id,grp,pts,gs,rank,group_size)
  with scores as (
    select m.player_a as user_id,m.grp,m.points_a as pts,coalesce(m.score_a,0) as gs from public.matches m where m.rnd=p_rnd and m.day=p_day and m.state in ('completed','forfeit')
    union all
    select m.player_b,m.grp,m.points_b,-coalesce(m.score_a,0) from public.matches m where m.rnd=p_rnd and m.day=p_day and m.state in ('completed','forfeit')
    union all
    select rb.user_id,rb.grp,0,0 from public.round_byes rb where rb.rnd=p_rnd and rb.day=p_day
  ), totals as (select sc.user_id,sc.grp,sum(sc.pts)::int as pts,sum(sc.gs)::int as gs from scores sc group by sc.user_id,sc.grp),
  prior_order as (select dr.user_id,avg(dr.rank)::numeric as avg_rank from public.daily_results dr
    where dr.rnd=p_rnd and dr.day<p_day group by dr.user_id), ranked as (
    select t.user_id,t.grp,t.pts,t.gs,count(*) over(partition by t.grp)::int as n,
      row_number() over(partition by t.grp order by t.pts desc,t.gs desc,
        case when p_day=1 then rm.seed else coalesce(po.avg_rank,rm.seed) end,rm.seed,rm.user_id)::int as r
    from totals t join public.round_members rm on rm.rnd=p_rnd and rm.user_id=t.user_id and rm.grp=t.grp
    left join prior_order po on po.user_id=t.user_id
  ) select p_rnd,p_day,rk.user_id,rk.grp,rk.pts,rk.gs,rk.r,rk.n from ranked rk;
  update public.contest_days set state='graded',graded_at=now(),
    publish_after=(date_trunc('day',now() at time zone 'Asia/Ho_Chi_Minh')+interval '1 day') at time zone 'Asia/Ho_Chi_Minh',
    total_matches=(select count(*) from public.matches m where m.rnd=p_rnd and m.day=p_day) where rnd=p_rnd and day=p_day;
  if p_day=cfg.days then
    insert into public.round_advancement(rnd,user_id,route,avg_rank_pct,final_rank)
    with cfg as (select rc.top_n,rc.wildcard_n from public.round_config rc where rc.rnd=p_rnd),
    final_day as (select dr.* from public.daily_results dr where dr.rnd=p_rnd and dr.day=p_day),
    history as (select dr.user_id,avg((dr.rank-1)::numeric/nullif(dr.group_size,0)) pct
      from public.daily_results dr where dr.rnd=p_rnd and dr.day<p_day group by dr.user_id),
    wildcard_order as (select fd.user_id,row_number() over(order by h.pct nulls last,fd.user_id) n
      from final_day fd cross join cfg c left join history h on h.user_id=fd.user_id where fd.rank>c.top_n),
    decision as (
      select rm.user_id,coalesce(h.pct,1) pct,fd.rank,
        case when fd.user_id is null then 'ineligible'::public.advance_route
          when fd.rank<=c.top_n then 'top'::public.advance_route
          when wo.n<=c.wildcard_n then 'wildcard'::public.advance_route
          else 'eliminated'::public.advance_route end route
      from public.round_members rm cross join cfg c
      left join final_day fd on fd.user_id=rm.user_id
      left join history h on h.user_id=rm.user_id
      left join wildcard_order wo on wo.user_id=rm.user_id
      where rm.rnd=p_rnd
    ) select p_rnd,d.user_id,d.route,d.pct,d.rank from decision d
    on conflict(rnd,user_id) do update set route=excluded.route,avg_rank_pct=excluded.avg_rank_pct,final_rank=excluded.final_rank;
    update public.profiles p set status=case when ra.route in ('top','wildcard') then 'active'::public.user_status else 'out'::public.user_status end
      from public.round_advancement ra where ra.rnd=p_rnd and ra.user_id=p.id;
    select count(*) into v_survivors from public.round_advancement ra where ra.rnd=p_rnd and ra.route in ('top','wildcard');
    v_next:=p_rnd+1;
    if v_next<=4 then
      insert into public.round_members(rnd,user_id,grp,seed)
      with ordered as (select p.id,p.entry_score,ra.avg_rank_pct,row_number() over(order by ra.avg_rank_pct,p.entry_score desc,p.id) pos
        from public.round_advancement ra join public.profiles p on p.id=ra.user_id where ra.rnd=p_rnd and ra.route in ('top','wildcard')),
      banded as (select o.*,ceil(o.pos::numeric/(select rc.num_groups from public.round_config rc where rc.rnd=v_next))::int band from ordered o),
      placed as (select b.*,row_number() over(partition by b.band order by md5(b.id::text||':'||v_next::text))-1 slot from banded b)
      select v_next,pl.id,(pl.slot%(select rc.num_groups from public.round_config rc where rc.rnd=v_next))::int,pl.pos::int from placed pl;
      insert into public.contest_days(rnd,day,state) values(v_next,1,'open') on conflict(rnd,day) do update set state='open';
      update public.tournament_state set current_round=v_next,current_day=1,pending_day=0,phase='round',accepting_submissions=false,updated_at=now() where id=1;
    else
      update public.tournament_state set phase='done',accepting_submissions=false,pending_day=0,updated_at=now() where id=1;
    end if;
  end if;
  return jsonb_build_object('round',p_rnd,'day',p_day,'survivors',v_survivors,'next_round',case when p_day=cfg.days and p_rnd<4 then p_rnd+1 else null end);
end $$;
revoke all on function public.finalize_tournament_day(int,int) from public,anon;
grant execute on function public.finalize_tournament_day(int,int) to authenticated,service_role;

create or replace function public.admin_set_submission_gate(p_accepting boolean)
returns public.tournament_state language plpgsql security definer set search_path = public as $$
declare v_state public.tournament_state;
begin
  if not public.is_admin() then raise exception 'admin_required' using errcode='42501'; end if;
  select * into v_state from public.tournament_state where id=1 for update;
  if not found then raise exception 'tournament_state_missing'; end if;
  if v_state.phase='done' and p_accepting then raise exception 'tournament_complete'; end if;
  update public.tournament_state set accepting_submissions=p_accepting,updated_at=now()
    where id=1 returning * into v_state;
  return v_state;
end $$;
revoke all on function public.admin_set_submission_gate(boolean) from public,anon;
grant execute on function public.admin_set_submission_gate(boolean) to authenticated;

-- Permit an authenticated admin to reset if the scoring endpoint is offline.
-- In this path, reject every active job because the browser cannot report the
-- scoring process's in-memory in-flight IDs to the reset transaction.
create or replace function public.admin_reset_tournament_to_entry(
  p_live_job_ids uuid[], p_live_match_ids bigint[]
)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_state public.tournament_state;
  v_jobs int;
  v_replays int;
  v_recovered_jobs int;
begin
  if auth.role() <> 'service_role' and not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
  end if;
  if p_live_job_ids is null or p_live_match_ids is null then raise exception 'live_work_ids_required'; end if;
  select * into v_state from public.tournament_state where id=1 for update;
  if not found then raise exception 'tournament_state_missing'; end if;
  if auth.role() <> 'service_role' and exists(select 1 from public.scoring_jobs sj
      where sj.status in ('dispatching','accepted','running')) then
    raise exception 'scoring_jobs_still_running' using errcode='55000';
  end if;
  if exists(select 1 from public.scoring_jobs sj
      where sj.status in ('dispatching','accepted','running')
        and (sj.id=any(p_live_job_ids) or coalesce(sj.started_at,sj.accepted_at,sj.created_at)>=now()-interval '15 minutes')) then
    raise exception 'scoring_jobs_still_running' using errcode='55000';
  end if;
  if exists(select 1 from public.matches m where m.state='running'
      and (m.id=any(p_live_match_ids) or m.started_at is null or m.started_at>=now()-interval '5 minutes')) then
    raise exception 'tournament_matches_still_running' using errcode='55000';
  end if;
  update public.scoring_jobs set status='failed',error_code='reset_orphaned_job',
    error_message='Yêu cầu chấm bị đóng khi reset giải đấu.',finished_at=now(),updated_at=now()
    where status in ('dispatching','accepted','running');
  get diagnostics v_recovered_jobs=row_count;
  insert into public.tournament_reset_source_cleanup(job_id)
    select sj.id from public.scoring_jobs sj on conflict(job_id) do nothing;
  insert into public.tournament_reset_cleanup(storage_path)
    select ro.storage_path from public.replay_objects ro on conflict(storage_path) do nothing;
  get diagnostics v_replays=row_count;
  delete from public.replay_objects;
  delete from public.submissions;
  delete from public.daily_results;
  delete from public.round_byes;
  delete from public.matches;
  delete from public.contest_days;
  delete from public.round_members;
  delete from public.round_advancement;
  delete from public.live_scores;
  delete from public.scoring_jobs;
  get diagnostics v_jobs=row_count;
  delete from public.admin_disqualifications;
  update public.profiles set status='new',entry_score=null where role='contestant';
  update public.tournament_state set phase='entry',current_round=0,current_day=0,pending_day=0,
    accepting_submissions=true,champion_id=null,updated_at=now() where id=1;
  return jsonb_build_object('status','reset','deleted_scoring_jobs',v_jobs,
    'recovered_orphaned_jobs',v_recovered_jobs,'queued_replay_cleanup',v_replays,
    'phase','entry','round',0,'day',0);
end $$;
revoke all on function public.admin_reset_tournament_to_entry(uuid[],bigint[]) from public,anon;
grant execute on function public.admin_reset_tournament_to_entry(uuid[],bigint[]) to authenticated,service_role;
