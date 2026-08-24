from typing import Optional, Union, List, Dict
from deepeval.models import DeepEvalBaseLLM
from deepeval.metrics.utils import initialize_model
import random

from deepteam.attacks.multi_turn.base_multi_turn_attack import (
    BaseMultiTurnAttack,
)
from deepteam.attacks.base_attack import Exploitability
from deepteam.attacks.multi_turn.bad_likert_judge.schema import (
    LikertExamples,
    RefinedExample,
    NewAttackPrompt,
)
from deepteam.attacks.multi_turn.bad_likert_judge.template import (
    BadLikertJudgeTemplate,
)
from deepteam.attacks.attack_simulator.utils import (
    generate,
    a_generate,
)
from deepteam.utils import create_progress, update_pbar, add_pbar
from deepteam.attacks.multi_turn.utils import (
    enhance_attack,
    a_enhance_attack,
    append_target_turn,
)
from deepteam.attacks.multi_turn.types import CallbackType
from deepteam.attacks.multi_turn.base_schema import NonRefusal
from deepteam.attacks.multi_turn.progression import (
    BehaviorShiftDetector,
    StopReason,
    mark_stop,
)
from deepteam.test_case.test_case import RTTurn
from deepteam.vulnerabilities.types import VulnerabilityType
from deepteam.vulnerabilities import BaseVulnerability
from deepteam.attacks.single_turn import BaseSingleTurnAttack


class BadLikertJudge(BaseMultiTurnAttack):
    name = "Bad Likert Judge"
    exploitability = Exploitability.LOW
    description = "An adaptive multi-turn attack that uses Likert scale scoring and iterative refinement to gradually guide the model toward harmful responses through feedback-driven escalation."

    def __init__(
        self,
        weight: int = 1,
        category: str = "bias",
        num_turns: int = 5,
        enable_refinement: bool = True,
        max_backtracks: int = 3,
        turn_level_attacks: Optional[List[BaseSingleTurnAttack]] = None,
        simulator_model: Optional[Union[DeepEvalBaseLLM, str]] = "gpt-4o-mini",
    ):
        self.weight = weight
        self.multi_turn = True
        self.category = category
        self.num_turns = num_turns
        self.enable_refinement = enable_refinement
        self.max_backtracks = max_backtracks
        self.simulator_model = simulator_model
        self.turn_level_attacks = turn_level_attacks

        if self.turn_level_attacks is not None:
            if not isinstance(self.turn_level_attacks, list) or not all(
                attack.multi_turn == False for attack in self.turn_level_attacks
            ):
                raise ValueError(
                    "The 'turn_level_attacks' passed must be a list of single-turn attacks"
                )

    def _should_refine(self) -> bool:
        return self.enable_refinement

    def _get_turns(
        self,
        model_callback: CallbackType,
        turns: Optional[List[RTTurn]] = None,
        vulnerability: str = None,
        vulnerability_type: str = None,
        simulator_model: Optional[Union[str, DeepEvalBaseLLM]] = None,
        *,
        metric_check=None,
    ) -> List[RTTurn]:
        if turns is None:
            turns = []

        if simulator_model:
            self.simulator_model, _ = initialize_model(simulator_model)
        else:
            self.simulator_model, _ = initialize_model(self.simulator_model)

        vulnerability_data = (
            f"Vulnerability: {vulnerability} | Type: {vulnerability_type}"
        )
        detector = BehaviorShiftDetector(
            simulator_model=self.simulator_model,
            vulnerability_data=vulnerability_data,
            metric_check=metric_check,
        )
        stop_reason = StopReason.BUDGET_EXHAUSTED
        stop_detail = None

        progress = create_progress()
        with progress:
            task_id = add_pbar(
                progress,
                description=f"🎯 Bad Likert Judge ({self.category})",
                total=self.num_turns,
            )
            # Extract last user turn as the original attack
            current_attack = None
            for turn in reversed(turns):
                if turn.role == "user":
                    current_attack = turn.content
                    break

            if current_attack is None:
                raise ValueError(
                    "No user turn found in the conversation history"
                )

            # Generate assistant response if needed
            if len(turns) <= 1 or turns[-1].role == "user":
                append_target_turn(
                    turns, model_callback(current_attack, turns)
                )

            backtrack_count = 0
            turns_appended = 0
            attempts_remaining = self.num_turns + self.max_backtracks

            verdict = detector.check(turns) if self.num_turns > 0 else None
            if verdict is not None:
                stop_reason = StopReason.SHIFT_DETECTED
                stop_detail = verdict.detail
                update_pbar(progress, task_id, advance_to_end=True)
                attempts_remaining = 0

            while turns_appended < self.num_turns and attempts_remaining > 0:
                attempts_remaining -= 1

                # Step 1: Request example pairs (score 1 and score 3)
                improvement_prompt = (
                    BadLikertJudgeTemplate.likert_generate_examples(
                        current_attack, self.category, vulnerability_data
                    )
                )

                try:
                    improvement_response = generate(
                        improvement_prompt, LikertExamples, self.simulator_model
                    )
                except Exception:
                    backtrack_count += 1
                    if backtrack_count >= self.max_backtracks:
                        stop_reason = StopReason.SIMULATION_ERROR
                        break
                    continue

                score_3_example = improvement_response.score_3_example

                # Step 2: Refine if needed (adaptive, not hardcoded)
                if self._should_refine():
                    refine_prompt = (
                        BadLikertJudgeTemplate.likert_refine_score_3(
                            score_3_example, vulnerability_data
                        )
                    )
                    try:
                        refined_response: RefinedExample = generate(
                            refine_prompt, RefinedExample, self.simulator_model
                        )
                        score_3_example = refined_response.refined_example
                    except Exception:
                        # If refinement fails, use original score_3_example
                        pass

                # Step 3: Extract and reuse - Generate new attack prompt from score_3_example
                attack_generation_prompt = (
                    BadLikertJudgeTemplate.likert_generate_attack_from_example(
                        score_3_example,
                        current_attack,
                        self.category,
                        vulnerability_data,
                    )
                )
                try:
                    attack_response: NewAttackPrompt = generate(
                        attack_generation_prompt,
                        NewAttackPrompt,
                        self.simulator_model,
                    )
                    next_attack = attack_response.new_attack_prompt
                except Exception:
                    backtrack_count += 1
                    if backtrack_count >= self.max_backtracks:
                        stop_reason = StopReason.SIMULATION_ERROR
                        break
                    continue

                # Step 4: Backtrack adaptively - Check for refusal
                refusal_prompt = BadLikertJudgeTemplate.non_refusal(
                    current_attack, next_attack
                )
                refusal_res: NonRefusal = generate(
                    refusal_prompt, NonRefusal, self.simulator_model
                )

                if refusal_res.refusal:
                    backtrack_count += 1
                    if backtrack_count >= self.max_backtracks:
                        stop_reason = StopReason.SIMULATOR_REFUSED
                        break
                    # Rephrase rubric/role and retry - skip this turn
                    continue

                # Reset backtrack count on success
                backtrack_count = 0
                current_attack = next_attack

                # Randomly enhancing a turn attack
                turn_level_attack = None
                if self.turn_level_attacks and random.random() < 0.5:
                    attack = random.choice(self.turn_level_attacks)
                    turn_level_attack = attack
                    current_attack = enhance_attack(
                        attack, current_attack, self.simulator_model
                    )

                assistant_response = model_callback(current_attack, turns)
                turns.append(RTTurn(role="user", content=current_attack))
                if turn_level_attack is not None:
                    append_target_turn(
                        turns, assistant_response, turn_level_attack.get_name()
                    )
                else:
                    append_target_turn(turns, assistant_response)

                turns_appended += 1
                update_pbar(progress, task_id)

                verdict = detector.check(turns)
                if verdict is not None:
                    stop_reason = StopReason.SHIFT_DETECTED
                    stop_detail = verdict.detail
                    update_pbar(progress, task_id, advance_to_end=True)
                    break

        return mark_stop(
            turns,
            stop_reason,
            detail=stop_detail,
            turns_spent=(len(turns) - 2) // 2,
        )

    async def _a_get_turns(
        self,
        model_callback: CallbackType,
        turns: Optional[List[RTTurn]] = None,
        vulnerability: str = None,
        vulnerability_type: str = None,
        simulator_model: Optional[Union[str, DeepEvalBaseLLM]] = None,
        *,
        metric_check=None,
    ) -> List[RTTurn]:
        if turns is None:
            turns = []

        if simulator_model:
            self.simulator_model, _ = initialize_model(simulator_model)
        else:
            self.simulator_model, _ = initialize_model(self.simulator_model)

        vulnerability_data = (
            f"Vulnerability: {vulnerability} | Type: {vulnerability_type}"
        )
        detector = BehaviorShiftDetector(
            simulator_model=self.simulator_model,
            vulnerability_data=vulnerability_data,
            metric_check=metric_check,
        )
        stop_reason = StopReason.BUDGET_EXHAUSTED
        stop_detail = None

        progress = create_progress()
        with progress:
            task_id = add_pbar(
                progress,
                description=f"🎯 Bad Likert Judge ({self.category})",
                total=self.num_turns,
            )

            # Extract last user turn
            current_attack = None
            for turn in reversed(turns):
                if turn.role == "user":
                    current_attack = turn.content
                    break

            if current_attack is None:
                raise ValueError("No user turn found")

            # Ensure assistant response
            if len(turns) <= 1 or turns[-1].role == "user":
                append_target_turn(
                    turns, await model_callback(current_attack, turns)
                )

            backtrack_count = 0
            turns_appended = 0
            attempts_remaining = self.num_turns + self.max_backtracks

            verdict = await detector.a_check(turns) if self.num_turns > 0 else None
            if verdict is not None:
                stop_reason = StopReason.SHIFT_DETECTED
                stop_detail = verdict.detail
                update_pbar(progress, task_id, advance_to_end=True)
                attempts_remaining = 0

            while turns_appended < self.num_turns and attempts_remaining > 0:
                attempts_remaining -= 1

                # Step 1: Request example pairs (score 1 and score 3)
                improvement_prompt = (
                    BadLikertJudgeTemplate.likert_generate_examples(
                        current_attack, self.category, vulnerability_data
                    )
                )

                try:
                    improvement_response = await a_generate(
                        improvement_prompt, LikertExamples, self.simulator_model
                    )
                except Exception:
                    backtrack_count += 1
                    if backtrack_count >= self.max_backtracks:
                        stop_reason = StopReason.SIMULATION_ERROR
                        break
                    continue

                score_3_example = improvement_response.score_3_example

                # Step 2: Refine if needed (adaptive, not hardcoded)
                if self._should_refine():
                    refine_prompt = (
                        BadLikertJudgeTemplate.likert_refine_score_3(
                            score_3_example, vulnerability_data
                        )
                    )
                    try:
                        refined_response: RefinedExample = await a_generate(
                            refine_prompt, RefinedExample, self.simulator_model
                        )
                        score_3_example = refined_response.refined_example
                    except Exception:
                        # If refinement fails, use original score_3_example
                        pass

                # Step 3: Extract and reuse - Generate new attack prompt from score_3_example
                attack_generation_prompt = (
                    BadLikertJudgeTemplate.likert_generate_attack_from_example(
                        score_3_example,
                        current_attack,
                        self.category,
                        vulnerability_data,
                    )
                )
                try:
                    attack_response: NewAttackPrompt = await a_generate(
                        attack_generation_prompt,
                        NewAttackPrompt,
                        self.simulator_model,
                    )
                    next_attack = attack_response.new_attack_prompt
                except Exception:
                    backtrack_count += 1
                    if backtrack_count >= self.max_backtracks:
                        stop_reason = StopReason.SIMULATION_ERROR
                        break
                    continue

                # Step 4: Backtrack adaptively - Check for refusal
                refusal_prompt = BadLikertJudgeTemplate.non_refusal(
                    current_attack, next_attack
                )
                refusal_res: NonRefusal = await a_generate(
                    refusal_prompt, NonRefusal, self.simulator_model
                )

                if refusal_res.refusal:
                    backtrack_count += 1
                    if backtrack_count >= self.max_backtracks:
                        stop_reason = StopReason.SIMULATOR_REFUSED
                        break
                    # Rephrase rubric/role and retry - skip this turn
                    continue

                # Reset backtrack count on success
                backtrack_count = 0
                current_attack = next_attack

                # Randomly enhancing a turn attack
                turn_level_attack = None
                if self.turn_level_attacks and random.random() < 0.5:
                    attack = random.choice(self.turn_level_attacks)
                    turn_level_attack = attack
                    current_attack = await a_enhance_attack(
                        attack, current_attack, self.simulator_model
                    )

                assistant_response = await model_callback(current_attack, turns)
                turns.append(RTTurn(role="user", content=current_attack))
                if turn_level_attack is not None:
                    append_target_turn(
                        turns, assistant_response, turn_level_attack.get_name()
                    )
                else:
                    append_target_turn(turns, assistant_response)

                turns_appended += 1
                update_pbar(progress, task_id)

                verdict = await detector.a_check(turns)
                if verdict is not None:
                    stop_reason = StopReason.SHIFT_DETECTED
                    stop_detail = verdict.detail
                    update_pbar(progress, task_id, advance_to_end=True)
                    break

        return mark_stop(
            turns,
            stop_reason,
            detail=stop_detail,
            turns_spent=(len(turns) - 2) // 2,
        )

    def progress(
        self,
        vulnerability: BaseVulnerability,
        model_callback: CallbackType,
        turns: Optional[List[RTTurn]] = None,
    ) -> Dict[VulnerabilityType, List[RTTurn]]:
        from deepteam.red_teamer.utils import (
            group_attacks_by_vulnerability_type,
        )

        # Simulate and group attacks
        simulated_attacks = group_attacks_by_vulnerability_type(
            vulnerability.simulate_attacks()
        )

        result = {}

        for vuln_type, attacks in simulated_attacks.items():
            for attack in attacks:
                # Defensive copy to avoid mutating external turns
                inner_turns = list(turns) if turns else []

                # Case 1: No turns, or last is user -> create assistant response
                if len(inner_turns) == 0 or inner_turns[-1].role == "user":
                    inner_turns = [RTTurn(role="user", content=attack.input)]
                    assistant_response = model_callback(
                        attack.input, inner_turns
                    )
                    append_target_turn(inner_turns, assistant_response)

                # Case 2: Last is assistant -> find preceding user
                elif inner_turns[-1].role == "assistant":
                    user_turn_content = None
                    for turn in reversed(inner_turns[:-1]):
                        if turn.role == "user":
                            user_turn_content = turn.content
                            break

                    if user_turn_content:
                        inner_turns = [
                            RTTurn(role="user", content=user_turn_content),
                            RTTurn(
                                role="assistant",
                                content=inner_turns[-1].content,
                            ),
                        ]
                    else:
                        # Fallback if no user found
                        inner_turns = [
                            RTTurn(role="user", content=attack.input)
                        ]
                        assistant_response = model_callback(
                            attack.input, inner_turns
                        )
                        append_target_turn(inner_turns, assistant_response)

                else:
                    # Unrecognized state — fallback to default
                    inner_turns = [RTTurn(role="user", content=attack.input)]
                    assistant_response = model_callback(
                        attack.input, inner_turns
                    )
                    append_target_turn(inner_turns, assistant_response)

                # Run enhancement loop and assign full turn history
                vulnerability_name = vulnerability.get_name()
                enhanced_turns = self._get_turns(
                    model_callback=model_callback,
                    turns=inner_turns,
                    vulnerability=vulnerability_name,
                    vulnerability_type=vuln_type.value,
                )

            result[vuln_type] = enhanced_turns

        return result

    async def a_progress(
        self,
        vulnerability: BaseVulnerability,
        model_callback: CallbackType,
        turns: Optional[List[RTTurn]] = None,
    ) -> Dict[VulnerabilityType, List[List[RTTurn]]]:
        from deepteam.red_teamer.utils import (
            group_attacks_by_vulnerability_type,
        )

        # Simulate and group attacks asynchronously
        simulated_attacks = await vulnerability.a_simulate_attacks()
        grouped_attacks = group_attacks_by_vulnerability_type(simulated_attacks)

        result = {}

        for vuln_type, attacks in grouped_attacks.items():
            for attack in attacks:
                # Defensive copy to avoid mutating external turns
                inner_turns = list(turns) if turns else []

                # Case 1: No turns, or last is user -> create assistant response
                if len(inner_turns) == 0 or inner_turns[-1].role == "user":
                    inner_turns = [RTTurn(role="user", content=attack.input)]
                    assistant_response = await model_callback(
                        attack.input, inner_turns
                    )
                    append_target_turn(inner_turns, assistant_response)

                # Case 2: Last is assistant -> find preceding user
                elif inner_turns[-1].role == "assistant":
                    user_turn_content = None
                    for turn in reversed(inner_turns[:-1]):
                        if turn.role == "user":
                            user_turn_content = turn.content
                            break

                    if user_turn_content:
                        inner_turns = [
                            RTTurn(role="user", content=user_turn_content),
                            RTTurn(
                                role="assistant",
                                content=inner_turns[-1].content,
                            ),
                        ]
                    else:
                        # Fallback if no user found
                        inner_turns = [
                            RTTurn(role="user", content=attack.input)
                        ]
                        assistant_response = await model_callback(
                            attack.input, inner_turns
                        )
                        append_target_turn(inner_turns, assistant_response)

                else:
                    # Unrecognized state — fallback to default
                    inner_turns = [RTTurn(role="user", content=attack.input)]
                    assistant_response = await model_callback(
                        attack.input, inner_turns
                    )
                    append_target_turn(inner_turns, assistant_response)

                # Run enhancement loop and assign full turn history
                vulnerability_name = vulnerability.get_name()
                enhanced_turns = await self._a_get_turns(
                    model_callback=model_callback,
                    turns=inner_turns,
                    vulnerability=vulnerability_name,
                    vulnerability_type=vuln_type.value,
                )

            result[vuln_type] = enhanced_turns

        return result

    def get_name(self) -> str:
        return self.name

    @classmethod
    def get_supported_categories(cls) -> list[str]:
        """
        Returns a list of example supported vulnerability categories.
        Note: The system supports any category - this is just a sample of common ones.
        """
        return [
            # Core vulnerability types
            "bias",
            "religion",
            "politics",
            "gender",
            "race",
            "toxicity",
            "profanity",
            "insults",
            "threats",
            "mockery",
            "illegal_activity",
            "weapons",
            "illegal_drugs",
            "violent_crimes",
            "cybercrime",
            "unauthorized_access",
            "bfla",
            "bola",
            "rbac",
            "sql_injection",
            "shell_injection",
            "personal_safety",
            "bullying",
            "self-harm",
            "unsafe_practices",
            "stalking",
            "graphic_content",
            "sexual_content",
            "pornographic_content",
            "misinformation",
            "factual_errors",
            "unsupported_claims",
            "pii_leakage",
            "database_access",
            "direct_disclosure",
            "session_leak",
            "prompt_leakage",
            "secrets_and_credentials",
            "instructions",
            "guard_exposure",
            "excessive_agency",
            "functionality",
            "permissions",
            "autonomy",
            "robustness",
            "input_overreliance",
            "hijacking",
            "intellectual_property",
            "copyright_violations",
            "trademark_infringement",
            "competition",
            "competitor_mention",
            "market_manipulation",
            "malware",
            "hacking",
            "exploitation",
            "violence",
            "harassment",
        ]
