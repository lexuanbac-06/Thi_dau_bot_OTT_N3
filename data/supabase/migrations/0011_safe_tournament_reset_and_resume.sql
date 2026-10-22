-- Serialize scoring submissions, match claims and tournament reset through the
-- single tournament_state row. Replay cleanup is queued so Storage deletion can
-- be retried independently after the database transaction commits.

create table if not exists public.tournament_reset_cleanup (
  storage_path text primary key,
  queued_at timestamptz not null default now()
);
alter table public.tournament_reset_cleanup enable row level security;
revoke all on public.tournament_reset_cleanup from public, anon, authenticated;

create table if not exists public.tournament_reset_source_cleanup (
  job_id uuid primary key,
  queued_at timestamptz not null default now()
);
alter table public.tournament_reset_source_cleanup enable row level security;
revoke all on public.tournament_reset_source_cleanup from public, anon, authenticated;

drop function if exists public.admin_reset_tournament_to_entry();
drop function if exists public.admin_reset_tournament_to_entry(uuid[]);
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
  if auth.role() <> 'service_role' then
    raise exception 'service_role_required' using errcode = '42501';
  end if;
  if p_live_job_ids is null or p_live_match_ids is null then
    raise exception 'live_work_ids_required';
  end if;

  -- Match claims and new scoring jobs take a compatible lock on this row.
  -- Reset's exclusive lock therefore freezes admission/claims until commit.
  select * into v_state from public.tournament_state where id = 1 for update;
  if not found then raise exception 'tournament_state_missing'; end if;

  if exists(select 1 from public.scoring_jobs
      where status in ('dispatching', 'accepted', 'running')
        and (id = any(p_live_job_ids)
          or coalesce(started_at, accepted_at, created_at) >= now() - interval '15 minutes')) then
    raise exception 'scoring_jobs_still_running' using errcode = '55000';
  end if;
  if exists(select 1 from public.matches where state = 'running'
      and (id = any(p_live_match_ids)
        or started_at is null or started_at >= now() - interval '5 minutes')) then
    raise exception 'tournament_matches_still_running' using errcode = '55000';
  end if;

  -- Jobs still marked active after a process restart are orphan records. Recent
  -- work and this module's in-flight IDs were rejected above.
  update public.scoring_jobs set status = 'failed', error_code = 'reset_orphaned_job',
    error_message = 'Yêu cầu chấm bị đóng khi reset giải đấu.', finished_at = now(), updated_at = now()
    where status in ('dispatching', 'accepted', 'running');
  get diagnostics v_recovered_jobs = row_count;

  insert into public.tournament_reset_source_cleanup(job_id)
    select id from public.scoring_jobs on conflict (job_id) do nothing;
  insert into public.tournament_reset_cleanup(storage_path)
    select storage_path from public.replay_objects
    on conflict (storage_path) do nothing;
  get diagnostics v_replays = row_count;

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
  get diagnostics v_jobs = row_count;

  -- A reset returns every contestant, including previously disqualified users,
  -- to a clean qualification state. Accounts and admin roles remain untouched.
  delete from public.admin_disqualifications;
  update public.profiles set status = 'new', entry_score = null
    where role = 'contestant';

  update public.tournament_state
    set phase = 'entry', current_round = 0, current_day = 0, pending_day = 0,
        accepting_submissions = true, champion_id = null, updated_at = now()
    where id = 1;

  return jsonb_build_object(
    'status', 'reset', 'deleted_scoring_jobs', v_jobs,
    'recovered_orphaned_jobs', v_recovered_jobs,
    'queued_replay_cleanup', v_replays,
    'phase', 'entry', 'round', 0, 'day', 0
  );
end $$;
revoke all on function public.admin_reset_tournament_to_entry(uuid[], bigint[]) from public, anon, authenticated;
grant execute on function public.admin_reset_tournament_to_entry(uuid[], bigint[]) to service_role;

create or replace function public.admin_list_reset_cleanup_paths(p_limit int default 500)
returns table(storage_path text)
language plpgsql stable security definer set search_path = public as $$
begin
  if auth.role() <> 'service_role' and not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
  end if;
  if p_limit < 1 or p_limit > 500 then raise exception 'invalid_cleanup_limit'; end if;
  return query select c.storage_path from public.tournament_reset_cleanup c
    order by c.queued_at, c.storage_path limit p_limit;
end $$;
revoke all on function public.admin_list_reset_cleanup_paths(int) from public, anon;
grant execute on function public.admin_list_reset_cleanup_paths(int) to authenticated, service_role;

create or replace function public.admin_ack_reset_cleanup_paths(p_paths text[])
returns int language plpgsql security definer set search_path = public as $$
declare v_deleted int;
begin
  if auth.role() <> 'service_role' and not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
  end if;
  if p_paths is null or cardinality(p_paths) > 500 then raise exception 'invalid_cleanup_paths'; end if;
  delete from public.tournament_reset_cleanup where storage_path = any(p_paths);
  get diagnostics v_deleted = row_count;
  return v_deleted;
end $$;
revoke all on function public.admin_ack_reset_cleanup_paths(text[]) from public, anon;
grant execute on function public.admin_ack_reset_cleanup_paths(text[]) to authenticated, service_role;

create or replace function public.admin_list_reset_source_cleanup_ids(p_limit int default 500)
returns table(job_id uuid)
language plpgsql stable security definer set search_path = public as $$
begin
  if auth.role() <> 'service_role' and not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
  end if;
  if p_limit < 1 or p_limit > 5000 then raise exception 'invalid_cleanup_limit'; end if;
  return query select c.job_id from public.tournament_reset_source_cleanup c
    order by c.queued_at, c.job_id limit p_limit;
end $$;
revoke all on function public.admin_list_reset_source_cleanup_ids(int) from public, anon;
grant execute on function public.admin_list_reset_source_cleanup_ids(int) to service_role;

create or replace function public.admin_ack_reset_source_cleanup_ids(p_job_ids uuid[])
returns int language plpgsql security definer set search_path = public as $$
declare v_deleted int;
begin
  if auth.role() <> 'service_role' and not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
  end if;
  if p_job_ids is null or cardinality(p_job_ids) > 5000 then raise exception 'invalid_cleanup_ids'; end if;
  delete from public.tournament_reset_source_cleanup where job_id = any(p_job_ids);
  get diagnostics v_deleted = row_count;
  return v_deleted;
end $$;
revoke all on function public.admin_ack_reset_source_cleanup_ids(uuid[]) from public, anon;
grant execute on function public.admin_ack_reset_source_cleanup_ids(uuid[]) to service_role;

-- Shared state locks allow concurrent submissions but make reset wait for any
-- in-flight job creation; jobs created after reset see the new entry context.
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

  select * into v_state from public.tournament_state where id = 1 for share;
  if not found or not v_state.accepting_submissions or v_state.phase = 'done' then
    raise exception 'submissions_closed' using errcode = '55000';
  end if;
  select * into v_profile from public.profiles where id = auth.uid() for update;
  if not found or v_profile.status = 'banned' then raise exception 'account_not_allowed' using errcode = '42501'; end if;

  if p_kind = 'entry' then
    if v_state.phase <> 'entry' then raise exception 'entry_closed' using errcode = '55000'; end if;
    if v_profile.status <> 'new' then raise exception 'entry_not_allowed' using errcode = '42501'; end if;
    select count(*) into v_attempts from public.scoring_jobs
      where user_id = auth.uid() and kind = 'entry' and status <> 'dispatch_failed';
    if v_attempts >= 20 then raise exception 'qualification_attempt_limit' using errcode = '54000'; end if;
  elsif p_kind = 'submission' then
    if v_state.phase <> 'round' or p_rnd is distinct from v_state.current_round
       or p_day is distinct from v_state.current_day then
      raise exception 'submission_context_stale' using errcode = '55000';
    end if;
    if v_profile.role <> 'admin' and (v_profile.status <> 'active'
       or not exists(select 1 from public.round_members rm where rm.rnd = p_rnd and rm.user_id = auth.uid())
       or exists(select 1 from public.round_config rc where rc.rnd = p_rnd and rc.is_offline)) then
      raise exception 'submission_not_allowed' using errcode = '42501';
    end if;
    if exists(select 1 from public.scoring_jobs j where j.user_id = auth.uid()
       and j.kind = 'submission' and j.rnd = p_rnd and j.day = p_day
       and j.status in ('dispatching', 'accepted', 'running', 'succeeded')) then
      raise exception 'already_submitted_today' using errcode = '23505';
    end if;
  elsif p_kind = 'test' then
    if p_rnd is not null or p_day is not null then raise exception 'invalid_test_context' using errcode = '22023'; end if;
  end if;

  insert into public.scoring_jobs(id, user_id, kind, rnd, day, sha256, size_bytes)
    values(p_job_id, auth.uid(), p_kind,
      case when p_kind = 'submission' then p_rnd end,
      case when p_kind = 'submission' then p_day end, p_sha256, p_size_bytes)
    returning * into v_job;
  return v_job;
exception when unique_violation then
  select * into v_job from public.scoring_jobs where id = p_job_id and user_id = auth.uid();
  if found then return v_job; end if;
  raise;
end $$;
revoke all on function public.create_scoring_job(uuid, text, int, int, text, int) from public, anon;
grant execute on function public.create_scoring_job(uuid, text, int, int, text, int) to authenticated;

-- Pair generation takes a shared state lock so reset cannot race new match rows.
create or replace function public.prepare_swiss_round(p_rnd int, p_day int, p_rd int)
returns table(match_id bigint, grp int, player_a uuid, player_b uuid,
              job_a uuid, job_b uuid, match_state text)
language plpgsql security definer set search_path = public as $$
declare
  v_state public.tournament_state;
  g record; v_order uuid[]; v_n int; v_half int;
  v_a uuid; v_b uuid; v_i int; v_j int;
begin
  if auth.role() <> 'service_role' and not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
  end if;
  select * into v_state from public.tournament_state where id = 1 for share;
  if not found or v_state.phase <> 'round' or v_state.current_round <> p_rnd
     or v_state.current_day <> p_day then
    raise exception 'round_context_stale' using errcode = '55000';
  end if;
  if p_rd < 1 or p_rd > 7 then raise exception 'invalid_match_round'; end if;
  if not exists(select 1 from public.contest_days
      where rnd = p_rnd and day = p_day and state in ('open', 'grading')) then
    raise exception 'day_not_open';
  end if;
  if p_rd > 1 and exists(select 1 from public.matches
      where rnd = p_rnd and day = p_day and rd = p_rd - 1
        and state not in ('completed', 'forfeit')) then
    raise exception 'previous_match_round_pending';
  end if;

  for g in select distinct rm.grp from public.round_members rm
      where rm.rnd = p_rnd order by rm.grp loop
    if p_rd = 1 then
      select array_agg(q.user_id order by q.avg_rank, q.seed, q.user_id)
        into v_order from (
          select rm.user_id, rm.seed,
            coalesce((select avg(dr.rank) from public.daily_results dr
              where dr.rnd = rm.rnd and dr.user_id = rm.user_id and dr.day < p_day), 0) avg_rank
          from public.round_members rm
          join public.profiles p on p.id = rm.user_id and p.status <> 'banned'
          where rm.rnd = p_rnd and rm.grp = g.grp
            and (p_day <> 7 or (select count(*) from public.submissions s
              where s.user_id = rm.user_id and s.rnd = p_rnd and s.day between 1 and 6) >= 4)
        ) q;
    else
      select array_agg(q.user_id order by q.points desc, q.avg_rank, q.seed, q.user_id)
        into v_order from (
          select rm.user_id, rm.seed,
            coalesce((select avg(dr.rank) from public.daily_results dr
              where dr.rnd = rm.rnd and dr.user_id = rm.user_id and dr.day < p_day), 0) avg_rank,
            coalesce((select sum(case when m.player_a = rm.user_id then m.points_a else m.points_b end)
              from public.matches m where m.rnd = p_rnd and m.day = p_day and m.rd < p_rd
                and m.state in ('completed', 'forfeit')
                and (m.player_a = rm.user_id or m.player_b = rm.user_id)), 0) points
          from public.round_members rm
          join public.profiles p on p.id = rm.user_id and p.status <> 'banned'
          where rm.rnd = p_rnd and rm.grp = g.grp
            and (p_day <> 7 or (select count(*) from public.submissions s
              where s.user_id = rm.user_id and s.rnd = p_rnd and s.day between 1 and 6) >= 4)
        ) q;
    end if;

    v_n := coalesce(array_length(v_order, 1), 0);
    if v_n = 0 then continue; end if;
    if v_n % 2 = 1 then
      v_a := null;
      for v_i in reverse v_n..1 loop
        if not exists(select 1 from public.round_byes b
            where b.rnd = p_rnd and b.grp = g.grp and b.user_id = v_order[v_i]) then
          v_a := v_order[v_i]; exit;
        end if;
      end loop;
      if v_a is null then v_a := v_order[v_n]; end if;
      insert into public.round_byes(rnd, day, rd, grp, user_id)
        values (p_rnd, p_day, p_rd, g.grp, v_a) on conflict do nothing;
      v_order := array_remove(v_order, v_a);
      v_n := coalesce(array_length(v_order, 1), 0);
      if v_n = 0 then continue; end if;
    end if;

    v_half := v_n / 2;
    if p_rd = 1 then
      for v_i in 1..v_half loop
        v_a := v_order[v_i]; v_b := v_order[v_i + v_half];
        insert into public.matches(rnd, day, rd, grp, player_a, player_b, state)
          values (p_rnd, p_day, p_rd, g.grp, v_a, v_b, 'pending')
          on conflict (rnd, day, rd, player_a, player_b) do nothing;
      end loop;
    else
      while coalesce(array_length(v_order, 1), 0) >= 2 loop
        v_a := v_order[1]; v_b := null;
        for v_j in 2..array_length(v_order, 1) loop
          if not exists(select 1 from public.matches old where old.rnd = p_rnd
              and old.grp = g.grp and old.day = p_day
              and ((old.player_a = v_a and old.player_b = v_order[v_j])
                or (old.player_a = v_order[v_j] and old.player_b = v_a))) then
            v_b := v_order[v_j]; exit;
          end if;
        end loop;
        if v_b is null then v_b := v_order[2]; end if;
        insert into public.matches(rnd, day, rd, grp, player_a, player_b, state)
          values (p_rnd, p_day, p_rd, g.grp, v_a, v_b, 'pending')
          on conflict (rnd, day, rd, player_a, player_b) do nothing;
        v_order := array_remove(array_remove(v_order, v_a), v_b);
      end loop;
    end if;
  end loop;

  return query select m.id, m.grp, m.player_a, m.player_b,
      sa.scoring_job_id, sb.scoring_job_id, m.state
    from public.matches m
    left join public.submissions sa on sa.user_id = m.player_a and sa.rnd = m.rnd and sa.day = m.day
    left join public.submissions sb on sb.user_id = m.player_b and sb.rnd = m.rnd and sb.day = m.day
    where m.rnd = p_rnd and m.day = p_day and m.rd = p_rd order by m.grp, m.id;
end $$;
revoke all on function public.prepare_swiss_round(int, int, int) from public, anon;
grant execute on function public.prepare_swiss_round(int, int, int) to authenticated, service_role;

-- Match claims serialize with reset and reject work for a stale tournament day.
create or replace function public.mark_tournament_match_running(p_match_id bigint)
returns boolean language plpgsql security definer set search_path = public as $$
declare
  v_state public.tournament_state;
  v_match public.matches;
  v_day_state public.day_state;
begin
  if auth.role() <> 'service_role' then
    raise exception 'service_role_required' using errcode = '42501';
  end if;
  select * into v_state from public.tournament_state where id = 1 for update;
  select * into v_match from public.matches where id = p_match_id for update;
  if v_state.id is null or not found or v_state.phase <> 'round'
     or v_match.rnd <> v_state.current_round or v_match.day <> v_state.current_day then
    return false;
  end if;
  select state into v_day_state from public.contest_days
    where rnd = v_match.rnd and day = v_match.day;
  if v_day_state is null or v_day_state not in ('open', 'grading') then return false; end if;
  if v_match.state <> 'pending' and not (
       v_match.state = 'running' and v_match.started_at < now() - interval '5 minutes'
     ) then
    return false;
  end if;
  update public.matches set state = 'running', started_at = now()
    where id = p_match_id;
  return true;
end $$;
revoke all on function public.mark_tournament_match_running(bigint) from public, anon, authenticated;
grant execute on function public.mark_tournament_match_running(bigint) to service_role;


-- Finalization is serialized with reset and safe to retry after a lost response.
create or replace function public.finalize_tournament_day(p_rnd int,p_day int)
returns jsonb language plpgsql security definer set search_path = public as $$
declare cfg public.round_config; v_state public.tournament_state; v_day_state public.day_state; v_next int; v_survivors int:=0;
begin
  if auth.role()<>'service_role' and not public.is_admin() then raise exception 'admin_required' using errcode='42501'; end if;
  select * into v_state from public.tournament_state where id=1 for update;
  if not found then raise exception 'tournament_state_missing'; end if;
  select state into v_day_state from public.contest_days where rnd=p_rnd and day=p_day;
  select * into cfg from public.round_config where rnd=p_rnd;
  if not found or p_day<1 or p_day>cfg.days then raise exception 'invalid_day'; end if;
  if v_day_state='graded' then
    return jsonb_build_object('round',p_rnd,'day',p_day,'survivors',
      (select count(*) from public.round_advancement where rnd=p_rnd and route in ('top','wildcard')),
      'next_round',case when p_day=cfg.days and p_rnd<4 then p_rnd+1 else null end,
      'already_finalized',true);
  end if;
  if v_state.phase<>'round' or v_state.current_round<>p_rnd or v_state.current_day<>p_day then
    raise exception 'round_context_stale' using errcode='55000';
  end if;
  if v_day_state is distinct from 'grading' then raise exception 'day_not_closed'; end if;
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
