-- Replay JSON is private in Supabase Storage. Object access is gated by the
-- associated match's group membership or the owner of a completed scoring job.

create table if not exists public.replay_objects (
  id bigint generated always as identity primary key,
  match_id bigint references public.matches(id) on delete cascade,
  job_id uuid references public.scoring_jobs(id) on delete cascade,
  storage_path text not null unique,
  content_type text not null default 'application/gzip',
  size_bytes bigint not null check (size_bytes > 0),
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  state text not null default 'ready' check (state in ('ready', 'failed')),
  created_at timestamptz not null default now(),
  check ((match_id is null) <> (job_id is null))
);
create unique index if not exists replay_objects_match_unique
  on public.replay_objects(match_id) where match_id is not null;
create unique index if not exists replay_objects_job_unique
  on public.replay_objects(job_id) where job_id is not null;

alter table public.replay_objects enable row level security;
drop policy if exists replay_objects_read_authorized on public.replay_objects;
create policy replay_objects_read_authorized on public.replay_objects
  for select to authenticated using (
    state = 'ready' and (
      (job_id is not null and exists (
        select 1 from public.scoring_jobs j
        where j.id = replay_objects.job_id and j.status = 'succeeded'
          and (j.user_id = auth.uid() or public.is_admin())
      ))
      or (match_id is not null and exists (
        select 1 from public.matches m
        where m.id = replay_objects.match_id and (
          public.is_admin() or exists (
            select 1 from public.round_members rm
            where rm.user_id = auth.uid() and rm.rnd = m.rnd and rm.grp = m.grp
          )
        ) and exists (
          select 1 from public.contest_days cd
          where cd.rnd = m.rnd and cd.day = m.day and cd.state = 'graded'
        )
      ))
    )
  );
revoke all on public.replay_objects from anon, authenticated;
grant select on public.replay_objects to authenticated;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('replays', 'replays', false, 16777216, array['application/gzip'])
on conflict (id) do update set public = false, file_size_limit = 16777216,
  allowed_mime_types = array['application/gzip'];

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
            where cd.rnd = m.rnd and cd.day = m.day and cd.state = 'graded'
          )
        ))
      )
    )
  );

drop function if exists public.get_my_replay_matches();
create function public.get_my_replay_matches()
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
  join public.contest_days cd on cd.rnd = m.rnd and cd.day = m.day and cd.state = 'graded'
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

create or replace function public.get_my_dashboard()
returns jsonb language sql stable security definer set search_path = public as $$
  with me as (
    select p.*, au.email from public.profiles p join auth.users au on au.id = p.id
    where p.id = auth.uid()
  ), state as (select * from public.tournament_state where id = 1),
  membership as (
    select rm.rnd, rm.grp from public.round_members rm
    join state s on s.current_round = rm.rnd where rm.user_id = auth.uid()
  ), days as (
    select coalesce(jsonb_agg(jsonb_build_object(
      'day', d.day, 'pts', d.pts, 'rank', d.rank, 'n', d.group_size
    ) order by d.day), '[]'::jsonb) value,
    avg(d.rank)::numeric(10,2) avg_rank
    from public.daily_results d join membership m on m.rnd = d.rnd and m.grp = d.grp
    where d.user_id = auth.uid()
  ), board as (
    select coalesce(jsonb_agg(jsonb_build_object(
      'rank', d.rank, 'name', p.username, 'pts', d.pts, 'gs', d.gs
    ) order by d.rank), '[]'::jsonb) value
    from public.daily_results d join membership m on m.rnd = d.rnd and m.grp = d.grp
    join public.profiles p on p.id = d.user_id
    where d.day = (select max(d2.day) from public.daily_results d2
                   where d2.rnd = d.rnd and d2.grp = d.grp)
  ), attempts as (
    select count(*)::int value from public.scoring_jobs
    where user_id = auth.uid() and kind = 'entry' and status <> 'dispatch_failed'
  ), champion as (
    select p.username from state s left join public.profiles p on p.id = s.champion_id
  )
  select jsonb_build_object(
    'status', (select jsonb_build_object(
      'name', me.username, 'email', me.email, 'role', me.role, 'status', me.status,
      'phase', state.phase, 'round', nullif(state.current_round, 0),
      'open_day', nullif(state.current_day, 0),
      'group', (select grp from membership limit 1),
      'entry', me.entry_score, 'avg_rank', days.avg_rank, 'days', days.value
    ) from me cross join state cross join days),
    'scoring', (select jsonb_build_object(
      'phase', state.phase, 'accepting', state.accepting_submissions,
      'attempts', attempts.value, 'bestScore', me.entry_score
    ) from state cross join me cross join attempts),
    'standings', (select value from board),
    'champion', (select username from champion)
  )
$$;
revoke all on function public.get_my_dashboard() from public, anon;
grant execute on function public.get_my_dashboard() to authenticated;

