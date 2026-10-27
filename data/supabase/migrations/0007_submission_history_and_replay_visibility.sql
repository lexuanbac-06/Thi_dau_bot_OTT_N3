-- Keep every user's own scoring history readable and delay group match replays
-- until the official standings publication time.
drop policy if exists replay_storage_read_authorized on storage.objects;
create policy replay_storage_read_authorized on storage.objects
  for select to authenticated using (
    bucket_id = 'replays' and exists (
      select 1 from public.replay_objects ro
      where ro.storage_path = storage.objects.name and ro.state = 'ready' and (
        (ro.job_id is not null and exists (
          select 1 from public.scoring_jobs j
          where j.id = ro.job_id and j.status = 'succeeded'
            and (j.user_id = auth.uid() or public.is_admin())
        ))
        or (ro.match_id is not null and exists (
          select 1 from public.matches m
          where m.id = ro.match_id and (
            public.is_admin() or exists (
              select 1 from public.round_members rm
              where rm.user_id = auth.uid() and rm.rnd = m.rnd and rm.grp = m.grp
            )
          ) and exists (
            select 1 from public.contest_days cd
            where cd.rnd = m.rnd and cd.day = m.day
              and cd.state = 'graded' and cd.publish_after <= now()
          )
        ))
      )
    )
  );

create or replace function public.get_my_replay_matches()
returns table (
  replay_id text, replay_kind text, rnd int, day int, rd int, grp int,
  player_a text, player_b text, score_a int, storage_path text
)
language sql stable security definer set search_path = public as $$
  select m.id::text, 'match'::text, m.rnd, m.day, m.rd, m.grp,
         pa.username, pb.username, m.score_a::int, ro.storage_path
  from public.matches m
  join public.replay_objects ro on ro.match_id = m.id and ro.state = 'ready'
  join public.profiles pa on pa.id = m.player_a
  join public.profiles pb on pb.id = m.player_b
  join public.contest_days cd on cd.rnd = m.rnd and cd.day = m.day
    and cd.state = 'graded' and cd.publish_after <= now()
  where m.has_replay and (public.is_admin() or exists (
    select 1 from public.round_members me
    where me.user_id = auth.uid() and me.rnd = m.rnd and me.grp = m.grp
  ))
  union all
  select j.id::text, 'job'::text, 0, 0,
         row_number() over (order by j.finished_at, j.id)::int,
         null::int, p.username, 'Bot mẫu',
         coalesce((j.result->>'match_score')::int, 0), ro.storage_path
  from public.scoring_jobs j
  join public.replay_objects ro on ro.job_id = j.id and ro.state = 'ready'
  join public.profiles p on p.id = j.user_id
  where j.status = 'succeeded' and (j.user_id = auth.uid() or public.is_admin())
  order by 3 desc, 4 desc, 5, 7
$$;
revoke all on function public.get_my_replay_matches() from public, anon;
grant execute on function public.get_my_replay_matches() to authenticated;
