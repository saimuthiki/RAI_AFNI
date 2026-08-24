import base64
from deepteam.attacks.single_turn import BaseSingleTurnAttack
from deepteam.attacks.base_attack import Exploitability


class Base64(BaseSingleTurnAttack):
    name = "Base64"
    exploitability = Exploitability.HIGH
    description = "An encoding-based attack that converts malicious prompts into Base64 format to bypass text-based content filters."

    def __init__(self, weight: int = 1):
        self.weight = weight

    def enhance(self, attack: str) -> str:
        """Enhance the attack using Base64 encoding."""
        return base64.b64encode(attack.encode()).decode()

    def get_name(self) -> str:
        return self.name
