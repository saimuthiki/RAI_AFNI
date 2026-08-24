from typing import Optional, Union, List, Dict
import random

from deepeval.models import DeepEvalBaseLLM
from deepeval.metrics.utils import initialize_model


from deepteam.attacks.multi_turn.linear_jailbreaking.schema import (
    Improvement,
    Feedback,
)
from deepteam.attacks.multi_turn.linear_jailbreaking.template import (
    JailBreakingTemplate,
)
from deepteam.attacks.attack_simulator.utils import (
    generate,
    a_generate,
)
from deepteam.attacks.multi_turn.types import CallbackType
from deepteam.utils import create_progress, update_pbar, add_pbar
from deepteam.attacks.single_turn import BaseSingleTurnAttack
from deepteam.attacks.base_attack import Exploitability
from deepteam.attacks.multi_turn.base_multi_turn_attack import (
    BaseMultiTurnAttack,
)
from deepteam.attacks.multi_turn.utils import (
    enhance_attack,
    a_enhance_attack,
    append_target_turn,
)
from deepteam.attacks.multi_turn.base_schema import NonRefusal
from deepteam.attacks.multi_turn.base_template import BaseMultiTurnTemplate
from deepteam.attacks.multi_turn.progression import (
    BehaviorShiftDetector,
    StopReason,
    mark_stop,
)
from deepteam.test_case.test_case import RTTurn
from deepteam.vulnerabilities.types import VulnerabilityType
from deepteam.vulnerabilities import BaseVulnerability


class LinearJailbreaking(BaseMultiTurnAttack):
    name = "Linear Jailbreaking"
    exploitability = Exploitability.LOW
    description = "An iterative multi-turn attack that uses LLM-as-judge feedback to refine prompts across turns, systematically improving attack effectiveness until jailbreak succeeds."

    def __init__(
        self,
        weight: int = 1,
        num_turns: int = 5,
        turn_level_attacks: Optional[List[BaseSingleTurnAttack]] = None,
        simulator_model: Optional[Union[DeepEvalBaseLLM, str]] = "gpt-4o-mini",
    ):
        self.weight = weight
        self.multi_turn = True
        self.num_turns = num_turns
        self.simulator_model = simulator_model
        self.turn_level_attacks = turn_level_attacks

        if self.turn_level_attacks is not None:
            if not isinstance(self.turn_level_attacks, list) or not all(
                attack.multi_turn == False for attack in self.turn_level_attacks
            ):
                raise ValueError(
                    "The 'turn_level_attacks' passed must be a list of single-turn attacks"
                )

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
                description="...... ⛓️  Linear Jailbreaking",
                total=self.num_turns,
            )

            # Get current attack from last user turn (simple reverse search)
            current_attack = None
            original_attack = None
            for turn in reversed(turns):
                if turn.role == "user":
                    current_attack = turn.content
                    original_attack = turn.content
                    break

            if current_attack is None:
                raise ValueError("No user turns found in conversation history")

            # If the last turn is from user, we need a model response before simulation
            if len(turns) <= 1 or turns[-1].role == "user":
                target_response = model_callback(current_attack, turns)
                append_target_turn(turns, target_response)
                last_response = target_response.content
            else:
                last_response = turns[-1].content

            # Main simulation loop
            for _ in range(self.num_turns):
                verdict = detector.check(turns)
                if verdict is not None:
                    stop_reason = StopReason.SHIFT_DETECTED
                    stop_detail = verdict.detail
                    update_pbar(progress, task_id, advance_to_end=True)
                    break

                judge_prompt = JailBreakingTemplate.linear_judge(
                    original_attack,
                    current_attack,
                    last_response,
                    vulnerability_data,
                )
                feedback: Feedback = generate(
                    judge_prompt, Feedback, self.simulator_model
                )

                improvement_prompt = JailBreakingTemplate.improvement_prompt(
                    turns, feedback.suggestion, vulnerability_data
                )
                improvement: Improvement = generate(
                    improvement_prompt, Improvement, self.simulator_model
                )
                next_attack = improvement.new_prompt

                non_refusal_prompt = BaseMultiTurnTemplate.non_refusal(
                    original_attack, next_attack
                )
                non_refusal_res: NonRefusal = generate(
                    non_refusal_prompt, NonRefusal, self.simulator_model
                )

                if non_refusal_res.refusal:
                    stop_reason = StopReason.SIMULATOR_REFUSED
                    update_pbar(progress, task_id, advance_to_end=True)
                    break

                current_attack = next_attack

                # Randomly enhancing a turn attack
                turn_level_attack = None
                if self.turn_level_attacks and random.random() < 0.5:
                    attack = random.choice(self.turn_level_attacks)
                    turn_level_attack = attack
                    current_attack = enhance_attack(
                        attack, current_attack, self.simulator_model
                    )

                target_response = model_callback(current_attack, turns)
                turns.append(RTTurn(role="user", content=current_attack))
                if turn_level_attack is not None:
                    append_target_turn(
                        turns, target_response, turn_level_attack.get_name()
                    )
                else:
                    append_target_turn(turns, target_response)
                last_response = target_response.content

                update_pbar(progress, task_id)
            else:
                verdict = (
                    detector.check(turns) if self.num_turns > 0 else None
                )
                if verdict is not None:
                    stop_reason = StopReason.SHIFT_DETECTED
                    stop_detail = verdict.detail

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
                description="...... ⛓️  Linear Jailbreaking",
                total=self.num_turns,
            )

            # Get current attack from last user turn (simple reverse search)
            current_attack = None
            original_attack = None
            for turn in reversed(turns):
                if turn.role == "user":
                    current_attack = turn.content
                    original_attack = turn.content
                    break

            if current_attack is None:
                raise ValueError("No user turns found in conversation history")

            # If last turn is user, generate a model response before the loop
            if len(turns) <= 1 or turns[-1].role == "user":
                target_response = await model_callback(current_attack, turns)
                append_target_turn(turns, target_response)
                last_response = target_response.content
            else:
                last_response = turns[-1].content

            # Main simulation loop
            for _ in range(self.num_turns):
                verdict = await detector.a_check(turns)
                if verdict is not None:
                    stop_reason = StopReason.SHIFT_DETECTED
                    stop_detail = verdict.detail
                    update_pbar(progress, task_id, advance_to_end=True)
                    break

                judge_prompt = JailBreakingTemplate.linear_judge(
                    original_attack,
                    current_attack,
                    last_response,
                    vulnerability_data,
                )
                feedback: Feedback = await a_generate(
                    judge_prompt, Feedback, self.simulator_model
                )

                improvement_prompt = JailBreakingTemplate.improvement_prompt(
                    turns, feedback.suggestion, vulnerability_data
                )
                improvement: Improvement = await a_generate(
                    improvement_prompt, Improvement, self.simulator_model
                )
                next_attack = improvement.new_prompt

                non_refusal_prompt = BaseMultiTurnTemplate.non_refusal(
                    original_attack, next_attack
                )
                non_refusal_res: NonRefusal = await a_generate(
                    non_refusal_prompt, NonRefusal, self.simulator_model
                )

                if non_refusal_res.refusal:
                    stop_reason = StopReason.SIMULATOR_REFUSED
                    update_pbar(progress, task_id, advance_to_end=True)
                    break

                current_attack = next_attack

                # Randomly enhancing a turn attack
                turn_level_attack = None
                if self.turn_level_attacks and random.random() < 0.5:
                    attack = random.choice(self.turn_level_attacks)
                    turn_level_attack = attack
                    current_attack = await a_enhance_attack(
                        attack, current_attack, self.simulator_model
                    )

                target_response = await model_callback(current_attack, turns)
                turns.append(RTTurn(role="user", content=current_attack))
                if turn_level_attack is not None:
                    append_target_turn(
                        turns, target_response, turn_level_attack.get_name()
                    )
                else:
                    append_target_turn(turns, target_response)
                last_response = target_response.content

                update_pbar(progress, task_id)
            else:
                verdict = (
                    await detector.a_check(turns) if self.num_turns > 0 else None
                )
                if verdict is not None:
                    stop_reason = StopReason.SHIFT_DETECTED
                    stop_detail = verdict.detail

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
    ) -> Dict[VulnerabilityType, List[RTTurn]]:
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
