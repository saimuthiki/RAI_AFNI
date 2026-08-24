import asyncio
import json
import random
import time
from typing import Dict, List, Optional, Tuple, Union

from deepeval.metrics.utils import initialize_model
from deepeval.models import DeepEvalBaseLLM

from deepteam.attacks import BaseAttack
from deepteam.attacks.attack_simulator.utils import a_generate, generate
from deepteam.attacks.base_attack import Exploitability
from deepteam.attacks.multi_turn.base_multi_turn_attack import (
    BaseMultiTurnAttack,
)
from deepteam.attacks.multi_turn.progression import (
    BehaviorShiftDetector,
    StopReason,
    mark_stop,
)
from deepteam.attacks.multi_turn.tree_jailbreaking.schema import (
    ImprovementPrompt,
    OnTopic,
    Rating,
)
from deepteam.attacks.multi_turn.tree_jailbreaking.template import (
    JailBreakingTemplate,
)
from deepteam.attacks.multi_turn.types import CallbackType
from deepteam.attacks.multi_turn.utils import (
    a_enhance_attack,
    append_target_turn,
    enhance_attack,
)
from deepteam.attacks.single_turn import BaseSingleTurnAttack
from deepteam.test_case.test_case import RTTurn
from deepteam.utils import add_pbar, create_progress, update_pbar
from deepteam.vulnerabilities import BaseVulnerability
from deepteam.vulnerabilities.types import VulnerabilityType


class TreeNode:
    def __init__(
        self,
        prompt: str,
        depth: int,
        conversation_history: Optional[List[dict]] = None,
        parent: Optional["TreeNode"] = None,
        turn_level_attack: Optional[BaseAttack] = None,
    ):
        self.prompt = prompt
        self.depth = depth
        self.parent = parent
        self.turn_level_attack = turn_level_attack
        self.conversation_history = conversation_history or []
        self.response: Optional[RTTurn] = None
        self.score: int = 0
        self.on_topic: bool = True


class TreeJailbreaking(BaseMultiTurnAttack):
    name = "Tree Jailbreaking"
    exploitability = Exploitability.LOW
    description = "A tree-search based multi-turn attack that explores multiple conversation branches in parallel, pruning low-scoring paths to find optimal jailbreak sequences."

    def __init__(
        self,
        weight: int = 1,
        max_depth: int = 10,
        branching_factor: int = 4,
        max_runtime: float = 600.0,
        turn_level_attacks: Optional[List[BaseSingleTurnAttack]] = None,
        simulator_model: Optional[Union[DeepEvalBaseLLM, str]] = "gpt-4o-mini",
    ):
        self.weight = weight
        self.multi_turn = True
        self.simulator_model = simulator_model
        self.max_depth = max_depth
        self.branching_factor = branching_factor
        self.max_runtime = max_runtime
        self.turn_level_attacks = turn_level_attacks
        self.search_log: List[dict] = []
        self.committed_path: List[TreeNode] = []

        if self.turn_level_attacks is not None:
            if not isinstance(self.turn_level_attacks, list) or not all(
                attack.multi_turn == False for attack in self.turn_level_attacks
            ):
                raise ValueError(
                    "The 'attacks' passed must be a list of single-turn attacks"
                )

    def _root_history(self, goal: str, vulnerability_data: str) -> List[dict]:
        return [
            {
                "role": "system",
                "content": JailBreakingTemplate.enhance_attack(
                    goal, vulnerability_data
                ),
            }
        ]

    @staticmethod
    def _branch_history(
        history: List[dict], goal: str, parent: Optional[TreeNode]
    ) -> List[dict]:
        history = list(history)
        history.append(
            {
                "role": "user",
                "content": (
                    f"Current prompt: {parent.prompt if parent else goal}\n\n"
                    f"OBJECTIVE: {goal}\n\n"
                    f"SCORE: {parent.score if parent else 0}"
                ),
            }
        )
        return history

    @staticmethod
    def _descend_history(node: TreeNode) -> List[dict]:
        history = list(node.conversation_history)
        history.append({"role": "assistant", "content": node.prompt})
        history.append(
            {
                "role": "user",
                "content": (
                    f"RESPONSE: {node.response.content if node.response else ''}"
                    f"\n\nSCORE: {node.score}"
                ),
            }
        )
        return history

    def _log(self, node: TreeNode, committed: bool):
        self.search_log.append(
            {
                "depth": node.depth,
                "prompt": node.prompt,
                "on_topic": node.on_topic,
                "score": node.score,
                "committed": committed,
            }
        )

    def _branch(
        self,
        goal: str,
        history: List[dict],
        parent: Optional[TreeNode],
        depth: int,
        vulnerability_data: str,
    ) -> Tuple[List[TreeNode], List[TreeNode]]:
        nodes: List[TreeNode] = []
        for _ in range(self.branching_factor):
            res: ImprovementPrompt = generate(
                json.dumps(history), ImprovementPrompt, self.simulator_model
            )
            prompt = res.prompt

            turn_level_attack = None
            if self.turn_level_attacks and random.random() < 0.5:
                attack = random.choice(self.turn_level_attacks)
                turn_level_attack = attack
                prompt = enhance_attack(attack, prompt, self.simulator_model)

            node = TreeNode(
                prompt=prompt,
                depth=depth,
                conversation_history=history,
                parent=parent,
                turn_level_attack=turn_level_attack,
            )
            topic: OnTopic = generate(
                JailBreakingTemplate.on_topic(goal, prompt, vulnerability_data),
                OnTopic,
                self.simulator_model,
            )
            node.on_topic = topic.on_topic
            nodes.append(node)

        return [n for n in nodes if n.on_topic], nodes

    async def _a_branch(
        self,
        goal: str,
        history: List[dict],
        parent: Optional[TreeNode],
        depth: int,
        vulnerability_data: str,
    ) -> Tuple[List[TreeNode], List[TreeNode]]:
        async def one() -> TreeNode:
            res: ImprovementPrompt = await a_generate(
                json.dumps(history), ImprovementPrompt, self.simulator_model
            )
            prompt = res.prompt

            turn_level_attack = None
            if self.turn_level_attacks and random.random() < 0.5:
                attack = random.choice(self.turn_level_attacks)
                turn_level_attack = attack
                prompt = await a_enhance_attack(
                    attack, prompt, self.simulator_model
                )

            node = TreeNode(
                prompt=prompt,
                depth=depth,
                conversation_history=history,
                parent=parent,
                turn_level_attack=turn_level_attack,
            )
            topic: OnTopic = await a_generate(
                JailBreakingTemplate.on_topic(goal, prompt, vulnerability_data),
                OnTopic,
                self.simulator_model,
            )
            node.on_topic = topic.on_topic
            return node

        nodes = list(
            await asyncio.gather(*[one() for _ in range(self.branching_factor)])
        )
        return [n for n in nodes if n.on_topic], nodes

    def _score(
        self,
        node: TreeNode,
        goal: str,
        turns: List[RTTurn],
        vulnerability_data: str,
        model_callback: CallbackType,
    ):
        node.response = model_callback(node.prompt, turns)
        rating: Rating = generate(
            JailBreakingTemplate.linear_judge(
                goal, node.prompt, node.response, vulnerability_data
            ),
            Rating,
            self.simulator_model,
        )
        node.score = rating.rating

    async def _a_score(
        self,
        node: TreeNode,
        goal: str,
        turns: List[RTTurn],
        vulnerability_data: str,
        model_callback: CallbackType,
    ):
        node.response = await model_callback(node.prompt, turns)
        rating: Rating = await a_generate(
            JailBreakingTemplate.linear_judge(
                goal, node.prompt, node.response, vulnerability_data
            ),
            Rating,
            self.simulator_model,
        )
        node.score = rating.rating

    def _commit(self, turns: List[RTTurn], node: TreeNode) -> List[RTTurn]:
        turns.append(RTTurn(role="user", content=node.prompt))
        append_target_turn(
            turns,
            node.response,
            node.turn_level_attack.get_name()
            if node.turn_level_attack is not None
            else None,
        )
        self.committed_path.append(node)
        self._log(node, committed=True)
        return turns

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

        self.model_callback = model_callback
        self.search_log = []
        self.committed_path = []

        goal = None
        for turn in reversed(turns):
            if turn.role == "user":
                goal = turn.content
                break

        if not goal:
            raise ValueError(
                "No user input found in the conversation to start from."
            )

        if len(turns) <= 1 or turns[-1].role == "user":
            append_target_turn(turns, model_callback(goal, turns))

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
        deadline = time.time() + self.max_runtime

        history = self._root_history(goal, vulnerability_data)
        parent = None

        progress = create_progress()
        with progress:
            task_id = add_pbar(
                progress,
                description="...... ⛓️  Tree Jailbreaking",
                total=self.max_depth,
            )

            for depth in range(1, self.max_depth + 1):
                if time.time() > deadline:
                    stop_reason = StopReason.RUNTIME_EXCEEDED
                    break

                branch_history = self._branch_history(history, goal, parent)
                candidates, all_nodes = self._branch(
                    goal, branch_history, parent, depth, vulnerability_data
                )
                if not candidates:
                    candidates, retry_nodes = self._branch(
                        goal, branch_history, parent, depth, vulnerability_data
                    )
                    if not candidates:
                        candidates = all_nodes + retry_nodes

                if not candidates:
                    stop_reason = StopReason.SIMULATION_ERROR
                    break

                for node in candidates:
                    self._score(
                        node,
                        goal,
                        turns,
                        vulnerability_data,
                        model_callback,
                    )

                best = max(candidates, key=lambda n: n.score)
                for node in candidates:
                    if node is not best:
                        self._log(node, committed=False)

                self._commit(turns, best)
                parent = best
                history = self._descend_history(best)
                update_pbar(progress, task_id)

                verdict = detector.check(turns)
                if verdict is not None:
                    stop_reason = StopReason.SHIFT_DETECTED
                    stop_detail = verdict.detail
                    break

            update_pbar(progress, task_id, advance_to_end=True)

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

        self.model_callback = model_callback
        self.search_log = []
        self.committed_path = []

        goal = None
        for turn in reversed(turns):
            if turn.role == "user":
                goal = turn.content
                break

        if not goal:
            raise ValueError(
                "No user input found in the conversation to start from."
            )

        if len(turns) <= 1 or turns[-1].role == "user":
            append_target_turn(turns, await model_callback(goal, turns))

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
        deadline = time.time() + self.max_runtime

        history = self._root_history(goal, vulnerability_data)
        parent = None

        progress = create_progress()
        with progress:
            task_id = add_pbar(
                progress,
                description="...... ⛓️  Tree Jailbreaking",
                total=self.max_depth,
            )

            for depth in range(1, self.max_depth + 1):
                if time.time() > deadline:
                    stop_reason = StopReason.RUNTIME_EXCEEDED
                    break

                branch_history = self._branch_history(history, goal, parent)
                candidates, all_nodes = await self._a_branch(
                    goal, branch_history, parent, depth, vulnerability_data
                )
                if not candidates:
                    candidates, retry_nodes = await self._a_branch(
                        goal, branch_history, parent, depth, vulnerability_data
                    )
                    if not candidates:
                        candidates = all_nodes + retry_nodes

                if not candidates:
                    stop_reason = StopReason.SIMULATION_ERROR
                    break

                await asyncio.gather(
                    *[
                        self._a_score(
                            node,
                            goal,
                            turns,
                            vulnerability_data,
                            model_callback,
                        )
                        for node in candidates
                    ]
                )

                best = max(candidates, key=lambda n: n.score)
                for node in candidates:
                    if node is not best:
                        self._log(node, committed=False)

                self._commit(turns, best)
                parent = best
                history = self._descend_history(best)
                update_pbar(progress, task_id)

                verdict = await detector.a_check(turns)
                if verdict is not None:
                    stop_reason = StopReason.SHIFT_DETECTED
                    stop_detail = verdict.detail
                    break

            update_pbar(progress, task_id, advance_to_end=True)

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

        self.simulator_model, _ = initialize_model(self.simulator_model)
        self.model_callback = model_callback

        simulated_attacks = vulnerability.simulate_attacks()
        grouped_attacks = group_attacks_by_vulnerability_type(simulated_attacks)

        result: Dict[VulnerabilityType, List[List[RTTurn]]] = {}

        for vuln_type, attacks in grouped_attacks.items():
            for attack in attacks:
                # Prepare vulnerability data string for prompt injection

                # Defensive copy of turns if any
                inner_turns = list(turns) if turns else []

                # Initialize conversation if needed
                if len(inner_turns) == 0 or inner_turns[-1].role == "user":
                    inner_turns = [RTTurn(role="user", content=attack.input)]
                    assistant_response = model_callback(
                        attack.input, inner_turns
                    )
                    append_target_turn(inner_turns, assistant_response)

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
                        inner_turns = [
                            RTTurn(role="user", content=attack.input)
                        ]
                        assistant_response = model_callback(
                            attack.input, inner_turns
                        )
                        append_target_turn(inner_turns, assistant_response)
                else:
                    inner_turns = [RTTurn(role="user", content=attack.input)]
                    assistant_response = model_callback(
                        attack.input, inner_turns
                    )
                    append_target_turn(inner_turns, assistant_response)

                # Run tree-based multi-turn search
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

        self.simulator_model, _ = initialize_model(self.simulator_model)
        self.model_callback = model_callback

        simulated_attacks = await vulnerability.a_simulate_attacks()
        grouped_attacks = group_attacks_by_vulnerability_type(simulated_attacks)

        result: Dict[VulnerabilityType, List[List[RTTurn]]] = {}

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
