# Lifted auto-eval: Qwen3-Coder-Next-FP8 (3 runs)

- Model: `Qwen/Qwen3-Coder-Next-FP8`
- Endpoint: `http://10.100.30.241:8801`
- Cases: **40** (`benchmark/lifted_auto_eval/`)
- Gold: `benchmark/lifted/`

## Aggregate per run

| Run | SMT equiv | Spec pre exact | Spec post exact | Code pre exact | Code post exact | Spec degraded |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 10/40 | 14/40 | 2/40 | 11/40 | 3/40 | 17/40 |
| 2 | 7/40 | 13/40 | 2/40 | 11/40 | 3/40 | 18/40 |
| 3 | 11/40 | 12/40 | 2/40 | 13/40 | 3/40 | 19/40 |

## SMT stability (3 runs)

- Always equivalent: **6**
- Never equivalent: **27**
- Mixed (1-2/3): **7**

## Per-case table

| Case | Frag | Attn | R1 | R2 | R3 | Spec post (1/2/3) | Code post (1/2/3) | Stable |
|---|---:|---:|---:|---:|---:|---|---:|
| `…r_examples_deal_correct_code_average.py_average` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…16_correct_code_chess.py_ChessPiece_can_move_to` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…hz_eprog_2019_exercise_03_problem_01.py_compute` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…contract_correct_code_showcase.py_compute_grade` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…ect_aoc2020_day_22_crab_combat.py_compute_score` | Y | Y | · | · | · | ·/·/· | ·/·/· | · |
| `…ect_aoc2020_day_17_conway_cubes.py_count_active` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…_handle_empty_directions_in_plan.py_count_flips` | Y | Y | Y | · | · | ·/·/· | ·/·/· | · |
| `…oc2020_day_3_toboggan_trajectory.py_count_trees` | Y | Y | · | · | · | ·/·/· | ·/·/· | · |
| `…tract_correct_code_showcase.py_csv_first_column` | Y |  | Y | Y | Y | ·/·/· | ·/·/· | Y |
| `…thz_eprog_2019_exercise_03_problem_04.py_decode` | N | Y | · | · | · | ·/·/· | ·/·/· | · |
| `…c2020_day_5_binary_boarding.py_determine_column` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…t_aoc2020_day_5_binary_boarding.py_determine_id` | Y |  | Y | Y | Y | Y/Y/Y | Y/Y/Y | Y |
| `…_aoc2020_day_5_binary_boarding.py_determine_row` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…y_5_binary_boarding.py_determine_row_and_column` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…ir_examples_PEP316_correct_code_arith.py_double` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…examples_icontract_correct_code_arith.py_double` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…ontract_correct_code_showcase.py_duplicate_list` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…mples_PEP316_correct_code_showcase.py_even_fibb` | Y |  | · | · | · | ·/·/· | Y/Y/Y | · |
| `…es_icontract_correct_code_showcase.py_even_fibb` | Y |  | Y | · | Y | ·/·/· | ·/·/· | · |
| `…20_day_18_operation_order.py_extract_expression` | Y | Y | · | · | · | ·/·/· | ·/·/· | · |
| `…aoc2020_day_13_shuttle_search.py_find_departure` | Y |  | Y | Y | Y | ·/·/· | ·/·/· | Y |
| `…c2020_day_1_report_repair.py_find_pair_with_sum` | Y |  | · | · | Y | ·/·/· | ·/·/· | · |
| `…t_ethz_eprog_2019_exercise_03_problem_03.py_gcd` | N | Y | Y | · | · | ·/·/· | ·/·/· | · |
| `…020_day_11_seating_system.py_list_neighbourhood` | Y |  | Y | Y | Y | ·/·/· | ·/·/· | Y |
| `…hz_eprog_2019_exercise_08_problem_01.py_matches` | N | Y | · | · | · | ·/·/· | ·/·/· | · |
| `…aoc2020_day_13_shuttle_search.py_next_departure` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…y_13_shuttle_search_wrong_mod.py_next_departure` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…s_PEP316_correct_code_arith.py_perimiter_length` | Y |  | Y | Y | Y | ·/·/· | ·/·/· | Y |
| `…contract_correct_code_arith.py_perimiter_length` | Y | Y | · | · | · | ·/·/· | ·/·/· | · |
| `…_aoc2020_day_20_jurassic_jigsaw.py_reverse_side` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…z_eprog_2019_exercise_08_problem_05.py_simulate` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…es_icontract_correct_code_arith.py_smallest_two` | N | Y | · | · | · | ·/·/· | ·/·/· | · |
| `…t_correct_aoc2020_day_9_encoding_error.py_solve` | Y | Y | · | Y | Y | ·/·/· | ·/·/· | · |
| `…hair_examples_PEP316_correct_code_arith.py_swap` | Y |  | · | · | · | ·/·/· | ·/·/· | · |
| `…r_examples_icontract_correct_code_arith.py_swap` | Y |  | · | · | · | Y/Y/Y | Y/Y/Y | · |
| `…rrect_aoc2020_day_25_combo_breaker.py_transform` | Y | Y | · | · | · | ·/·/· | ·/·/· | · |
| `…6_correct_code_numpy_examples.py_unit_normalize` | Y | Y | · | · | Y | ·/·/· | ·/·/· | · |
| `…ect_aoc2020_day_2_password_philosophy.py_verify` | Y | Y | · | · | · | ·/·/· | ·/·/· | · |
| `…es_icontract_correct_code_showcase.py_zip_exact` | Y |  | Y | Y | Y | ·/·/· | ·/·/· | Y |
| `…icontract_correct_code_showcase.py_zipped_pairs` | Y |  | Y | · | Y | ·/·/· | ·/·/· | · |

## Files

- `cases.csv` — per-case metrics for all 3 runs
- `summary.json` — aggregate counters
- `run_01_*.json` … `run_03_*.json` — raw Dualify reports

Legend: **R1/R2/R3** = SMT equivalent; **Spec/Code post** = exact match vs gold post; **Frag** = gold in_fragment; **Attn** = needs_attention.
