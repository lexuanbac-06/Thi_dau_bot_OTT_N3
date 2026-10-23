-- OTT tournament schema for Supabase (Postgres 15+).
-- Chạy trong Supabase Dashboard > SQL Editor (hoặc `supabase db push`).
-- Có thể chạy lại nhiều lần (idempotent).

-- ============ ENUM ============
do $$ begin
  create type public.user_role     as enum ('contestant', 'admin');
  exception when duplicate_object then null; end $$;
do $$ begin
  create type public.user_status   as enum ('new', 'active', 'out', 'banned');
  exception when duplicate_object then null; end $$;
do $$ begin
  create type public.tour_phase    as enum ('entry', 'round', 'done');
  exception when duplicate_object then null; end $$;
do $$ begin
  create type public.day_state     as enum ('open', 'closed', 'grading', 'graded');
  exception when duplicate_object then null; end $$;
do $$ begin
  create type public.advance_route as enum ('top', 'wildcard', 'eliminated', 'ineligible');
  exception when duplicate_object then null; end $$;

-- ============ USER ============
create table if not exists public.profiles (
  id             uuid primary key references auth.users(id) on delete cascade,
  username       text not null check (username ~ '^[A-Za-z0-9_]{3,20}$'),
  role           public.user_role   not null default 'contestant',
  status         public.user_status not null default 'new',
  entry_score    numeric,
  created_at     timestamptz not null default now(),
  last_login_at  timestamptz,
  last_logout_at timestamptz
);
create unique index if not exists profiles_username_lower_key on public.profiles (lower(username));
create index if not exists profiles_status_idx on public.profiles (status);

create table if not exists public.auth_events (
  id         bigint generated always as identity primary key,
  user_id    uuid references public.profiles(id) on delete set null,
  username   text,
  event      text not null check (event in ('register', 'login', 'login_failed', 'logout')),
  ip         text,
  user_agent text,
  created_at timestamptz not null default now()
);
create index if not exists auth_events_user_idx on public.auth_events (user_id, created_at desc);

-- Tự tạo profile khi có user mới trong auth.users (username lấy từ user_metadata).
-- Role luôn là contestant: nâng admin bằng SQL thủ công.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, username)
  values (new.id, new.raw_user_meta_data ->> 'username');
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ============ GIẢI ĐẤU ============
create table if not exists public.tournament_state (
  id                    smallint primary key default 1 check (id = 1),
  phase                 public.tour_phase not null default 'entry',
  current_round         int  not null default 0,
  current_day           int  not null default 0,
  pending_day           int  not null default 0,   -- ngày đã chốt, chờ chấm (0 = không có)
  accepting_submissions boolean not null default true,
  champion_id           uuid references public.profiles(id) on delete set null,
  updated_at            timestamptz not null default now()
);
insert into public.tournament_state (id) values (1) on conflict do nothing;

create table if not exists public.round_config (
  rnd             int primary key check (rnd >= 1),
  num_groups      int not null check (num_groups >= 1),   -- số bảng
  top_n           int not null check (top_n >= 0),        -- top mỗi bảng đi tiếp
  wildcard_n      int not null default 0 check (wildcard_n >= 0), -- vé vớt toàn vòng
  days            int not null default 7,
  min_days        int not null default 4,                 -- phải nộp >= min_days trong (days-1) ngày đầu
  matches_per_day int not null default 7,
  is_offline      boolean not null default false
);

-- user <-> vòng <-> bảng
create table if not exists public.round_members (
  rnd     int  not null references public.round_config(rnd) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  grp     int  not null check (grp >= 0),
  seed    int  not null,                        -- thứ tự ban đầu (0 = mạnh nhất)
  primary key (rnd, user_id)
);
create index if not exists round_members_grp_idx on public.round_members (rnd, grp, seed);

create table if not exists public.contest_days (
  rnd          int not null references public.round_config(rnd) on delete cascade,
  day          int not null check (day >= 1),
  state        public.day_state not null default 'open',
  closed_at    timestamptz,
  graded_at    timestamptz,
  total_matches int,
  primary key (rnd, day)
);

-- Chỉ metadata; code bot nằm ở máy local. rnd=0, day=0 là thi đầu vào.
create table if not exists public.submissions (
  user_id      uuid not null references public.profiles(id) on delete cascade,
  rnd          int  not null,
  day          int  not null,
  submitted_at timestamptz not null default now(),
  sha256       text,
  size_bytes   int,
  primary key (user_id, rnd, day)
);

create table if not exists public.daily_results (
  rnd        int  not null,
  day        int  not null,
  user_id    uuid not null references public.profiles(id) on delete cascade,
  grp        int  not null,
  pts        int  not null,
  gs         int  not null,
  rank       int  not null,
  group_size int  not null,
  primary key (rnd, day, user_id)
);
create index if not exists daily_results_grp_idx on public.daily_results (rnd, day, grp, rank);

create table if not exists public.matches (
  id         bigint generated always as identity primary key,
  rnd        int  not null,
  day        int  not null,
  rd         int  not null,                      -- lượt ghép (1..7)
  grp        int  not null,
  player_a   uuid not null references public.profiles(id) on delete cascade,
  player_b   uuid not null references public.profiles(id) on delete cascade,
  score_a    smallint not null check (score_a between -2 and 2), -- tổng 2 ván của A
  has_replay boolean not null default false,
  unique (rnd, day, rd, player_a, player_b)
);
create index if not exists matches_day_grp_idx on public.matches (rnd, day, grp);
create index if not exists matches_a_idx on public.matches (player_a);
create index if not exists matches_b_idx on public.matches (player_b);

create table if not exists public.round_advancement (
  rnd          int  not null references public.round_config(rnd) on delete cascade,
  user_id      uuid not null references public.profiles(id) on delete cascade,
  route        public.advance_route not null,
  avg_rank_pct numeric,                           -- trung bình (hạng-1)/group_size, thấp = tốt
  final_rank   int,
  primary key (rnd, user_id)
);

create table if not exists public.live_scores (
  id         bigint generated always as identity primary key,
  event      text not null check (char_length(event) between 1 and 80),
  user_id    uuid not null references public.profiles(id) on delete cascade,
  score      double precision not null,
  updated_at timestamptz not null default now(),
  unique (event, user_id)
);

-- ============ VIEW ============
create or replace view public.v_avg_rank with (security_invoker = true) as
  select rnd, user_id,
         avg(rank)::numeric(10,2)                       as avg_rank,
         avg((rank - 1)::numeric / group_size)          as avg_rank_pct,
         count(*)                                       as days_ranked
  from public.daily_results
  group by rnd, user_id;

create or replace view public.v_submission_counts with (security_invoker = true) as
  select s.user_id, s.rnd, count(*) as days_submitted
  from public.submissions s
  join public.round_config rc on rc.rnd = s.rnd and s.day < rc.days
  group by s.user_id, s.rnd;

-- ============ HÀM PHÂN QUYỀN ============
create or replace function public.is_admin()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.profiles where id = auth.uid() and role = 'admin');
$$;

-- BXH cả bảng của người gọi (ngày mới nhất nếu p_day null). Thí sinh không đọc bảng khác.
create or replace function public.get_group_leaderboard(p_rnd int, p_day int default null)
returns table (rank int, username text, pts int, gs int, group_size int, day int)
language sql stable security definer set search_path = public as $$
  select d.rank, p.username, d.pts, d.gs, d.group_size, d.day
  from public.round_members me
  join public.daily_results d on d.rnd = me.rnd and d.grp = me.grp
  join public.profiles p on p.id = d.user_id
  where me.user_id = auth.uid() and me.rnd = p_rnd
    and d.day = coalesce(p_day, (select max(x.day) from public.daily_results x
                                 where x.rnd = me.rnd and x.grp = me.grp))
  order by d.rank;
$$;

-- Các trận của bảng mình trong 1 ngày đã chấm xong.
create or replace function public.get_group_matches(p_rnd int, p_day int)
returns table (match_id bigint, rd int, player_a text, player_b text, score_a smallint, has_replay boolean)
language sql stable security definer set search_path = public as $$
  select m.id, m.rd, pa.username, pb.username, m.score_a, m.has_replay
  from public.round_members me
  join public.matches m on m.rnd = me.rnd and m.grp = me.grp
  join public.profiles pa on pa.id = m.player_a
  join public.profiles pb on pb.id = m.player_b
  where me.user_id = auth.uid() and me.rnd = p_rnd and m.day = p_day
    and exists (select 1 from public.contest_days cd
                where cd.rnd = m.rnd and cd.day = m.day and cd.state = 'graded')
  order by m.rd, pa.username;
$$;

-- Dùng bởi storage server (local): trả vị trí file replay nếu người gọi được phép xem.
create or replace function public.get_replay_ref(p_match_id bigint)
returns table (rnd int, day int, rd int, grp int, player_a text, player_b text)
language sql stable security definer set search_path = public as $$
  select m.rnd, m.day, m.rd, m.grp, pa.username, pb.username
  from public.matches m
  join public.profiles pa on pa.id = m.player_a
  join public.profiles pb on pb.id = m.player_b
  where m.id = p_match_id and m.has_replay
    and exists (select 1 from public.contest_days cd
                where cd.rnd = m.rnd and cd.day = m.day and cd.state = 'graded')
    and (public.is_admin()
         or exists (select 1 from public.round_members me
                    where me.user_id = auth.uid() and me.rnd = m.rnd and me.grp = m.grp));
$$;

-- Chỉ người đã đăng nhập mới gọi được các hàm; anon bị chặn.
revoke all on function public.get_group_leaderboard(int, int) from public, anon;
revoke all on function public.get_group_matches(int, int)     from public, anon;
revoke all on function public.get_replay_ref(bigint)          from public, anon;
grant execute on function public.get_group_leaderboard(int, int) to authenticated;
grant execute on function public.get_group_matches(int, int)     to authenticated;
grant execute on function public.get_replay_ref(bigint)          to authenticated;
grant execute on function public.is_admin()                      to authenticated;

-- ============ RLS ============
alter table public.profiles          enable row level security;
alter table public.auth_events       enable row level security;
alter table public.tournament_state  enable row level security;
alter table public.round_config      enable row level security;
alter table public.round_members     enable row level security;
alter table public.contest_days      enable row level security;
alter table public.submissions       enable row level security;
alter table public.daily_results     enable row level security;
alter table public.matches           enable row level security;
alter table public.round_advancement enable row level security;
alter table public.live_scores       enable row level security;

-- Không có policy INSERT/UPDATE/DELETE cho client: chỉ service_role (bỏ qua RLS) được ghi.
drop policy if exists profiles_self_read on public.profiles;
create policy profiles_self_read on public.profiles for select to authenticated
  using (id = auth.uid() or public.is_admin());

drop policy if exists auth_events_self_read on public.auth_events;
create policy auth_events_self_read on public.auth_events for select to authenticated
  using (user_id = auth.uid() or public.is_admin());

drop policy if exists state_read on public.tournament_state;
create policy state_read on public.tournament_state for select to authenticated using (true);

drop policy if exists round_config_read on public.round_config;
create policy round_config_read on public.round_config for select to authenticated using (true);

drop policy if exists members_self_read on public.round_members;
create policy members_self_read on public.round_members for select to authenticated
  using (user_id = auth.uid() or public.is_admin());

drop policy if exists days_read on public.contest_days;
create policy days_read on public.contest_days for select to authenticated using (true);

drop policy if exists submissions_self_read on public.submissions;
create policy submissions_self_read on public.submissions for select to authenticated
  using (user_id = auth.uid() or public.is_admin());

drop policy if exists daily_self_read on public.daily_results;
create policy daily_self_read on public.daily_results for select to authenticated
  using (user_id = auth.uid() or public.is_admin());

drop policy if exists matches_self_read on public.matches;
create policy matches_self_read on public.matches for select to authenticated
  using (player_a = auth.uid() or player_b = auth.uid() or public.is_admin());

drop policy if exists advancement_self_read on public.round_advancement;
create policy advancement_self_read on public.round_advancement for select to authenticated
  using (user_id = auth.uid() or public.is_admin());

-- live_scores (điểm offline) hiển thị công khai cho người đã đăng nhập.
drop policy if exists live_scores_read on public.live_scores;
create policy live_scores_read on public.live_scores for select to authenticated using (true);
