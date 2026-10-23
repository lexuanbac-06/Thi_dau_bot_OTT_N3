-- Persist an immutable JSON rule snapshot per round and allow admins to choose
-- one of the checked-in rule presets before that round starts.

alter table public.round_config
  add column if not exists game_rule_key text not null default 'rule1'
    check (game_rule_key in ('rule1', 'rule2', 'rule3', 'rule4', 'rule5')),
  add column if not exists game_rules jsonb not null default
    '{"schema_version":1,"board":{"width":9,"height":9,"walls":[],"protection_zones":[],"teleporters":[],"piece_changers":[]}}'::jsonb;

create or replace function public.admin_set_round_game_rules(
  p_rnd int,
  p_rule_key text,
  p_rules jsonb
)
returns public.round_config
language plpgsql security definer set search_path = public as $$
declare
  v_state public.tournament_state;
  v_config public.round_config;
begin
  if not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
  end if;
  if p_rnd < 1 or p_rnd > 4
     or p_rule_key not in ('rule1', 'rule2', 'rule3', 'rule4', 'rule5') then
    raise exception 'invalid_round_rule' using errcode = '22023';
  end if;
  if jsonb_typeof(p_rules) is distinct from 'object'
     or p_rules->>'schema_version' is distinct from '1'
     or jsonb_typeof(p_rules->'board') is distinct from 'object'
     or (p_rules->'board'->>'width') is distinct from '9'
     or (p_rules->'board'->>'height') is distinct from '9'
     or jsonb_typeof(p_rules->'board'->'walls') is distinct from 'array'
     or jsonb_typeof(p_rules->'board'->'protection_zones') is distinct from 'array'
     or jsonb_typeof(p_rules->'board'->'teleporters') is distinct from 'array'
     or jsonb_typeof(p_rules->'board'->'piece_changers') is distinct from 'array' then
    raise exception 'invalid_game_rules' using errcode = '22023';
  end if;

  select * into v_state
    from public.tournament_state
   where id = 1
   for update;
  if not found then raise exception 'tournament_state_missing'; end if;
  if v_state.phase = 'done'
     or (v_state.phase = 'round' and v_state.current_round >= p_rnd)
     or exists (select 1 from public.matches m where m.rnd = p_rnd) then
    raise exception 'round_rules_locked' using errcode = '55000';
  end if;

  update public.round_config
     set game_rule_key = p_rule_key,
         game_rules = p_rules
   where rnd = p_rnd
   returning * into v_config;
  if not found then raise exception 'round_not_configured'; end if;
  return v_config;
end $$;

revoke all on function public.admin_set_round_game_rules(int, text, jsonb) from public, anon;
grant execute on function public.admin_set_round_game_rules(int, text, jsonb) to authenticated;
