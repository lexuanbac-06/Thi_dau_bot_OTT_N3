-- Handle a one-player eligible group: record its bye and skip empty pairing loops.

create or replace function public.prepare_swiss_round(p_rnd int, p_day int, p_rd int)
returns table(match_id bigint, grp int, player_a uuid, player_b uuid,
              job_a uuid, job_b uuid, match_state text)
language plpgsql security definer set search_path = public as $$
declare
  g record; v_order uuid[]; v_n int; v_half int;
  v_a uuid; v_b uuid; v_i int; v_j int;
begin
  if auth.role() <> 'service_role' and not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
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
