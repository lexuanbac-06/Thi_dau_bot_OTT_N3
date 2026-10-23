-- Persist the fixed, cumulative game-rule preset assigned to each online round.

alter table public.round_config
  add column if not exists game_rule_key text not null default 'rule1'
    check (game_rule_key in ('rule1', 'rule2', 'rule3', 'rule4', 'rule5')),
  add column if not exists game_rules jsonb not null default
    '{"schema_version":1,"board":{"width":9,"height":9,"walls":[],"protection_zones":[],"teleporters":[],"piece_changers":[]}}'::jsonb;

update public.round_config
set game_rule_key = 'rule' || rnd::text,
    game_rules = case rnd
      when 1 then jsonb_build_object(
        'schema_version', 1,
        'board', jsonb_build_object(
          'width', 9, 'height', 9,
          'walls', '[]'::jsonb,
          'protection_zones', '[]'::jsonb,
          'teleporters', '[]'::jsonb,
          'piece_changers', '[]'::jsonb
        )
      )
      when 2 then jsonb_build_object(
        'schema_version', 1,
        'board', jsonb_build_object(
          'width', 9, 'height', 9,
          'walls', '[[3,3],[4,3],[5,3],[3,5],[4,5],[5,5]]'::jsonb,
          'protection_zones', '[]'::jsonb,
          'teleporters', '[]'::jsonb,
          'piece_changers', '[]'::jsonb
        )
      )
      when 3 then jsonb_build_object(
        'schema_version', 1,
        'board', jsonb_build_object(
          'width', 9, 'height', 9,
          'walls', '[[3,3],[4,3],[5,3],[3,5],[4,5],[5,5]]'::jsonb,
          'protection_zones', '[[[2,1],[3,1]],[[5,7],[6,7]],[[1,3],[2,3]],[[6,5],[7,5]]]'::jsonb,
          'teleporters', '[]'::jsonb,
          'piece_changers', '[]'::jsonb
        )
      )
      when 4 then jsonb_build_object(
        'schema_version', 1,
        'board', jsonb_build_object(
          'width', 9, 'height', 9,
          'walls', '[[3,3],[4,3],[5,3],[3,5],[4,5],[5,5]]'::jsonb,
          'protection_zones', '[[[2,1],[3,1]],[[5,7],[6,7]],[[1,3],[2,3]],[[6,5],[7,5]]]'::jsonb,
          'teleporters', '[{"ends":[[1,2],[7,6]],"activation":"piece_starts_turn_on_endpoint","use":"optional","occupied_destination":"capture_if_legal"},{"ends":[[2,6],[6,2]],"activation":"piece_starts_turn_on_endpoint","use":"optional","occupied_destination":"capture_if_legal"},{"ends":[[4,1],[4,7]],"activation":"piece_starts_turn_on_endpoint","use":"optional","occupied_destination":"capture_if_legal"}]'::jsonb,
          'piece_changers', '[]'::jsonb
        )
      )
    end
where rnd between 1 and 4;
