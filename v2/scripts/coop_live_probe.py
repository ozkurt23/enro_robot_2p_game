"""Real Qwen -> persona -> two-player consent, without issuing physical actions."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from enro_terminal.coop import CoopSession, MISSIONS, Phase, ProposalExecutor
from enro_terminal.dialogue import QwenPersonaActor
from enro_terminal.game import TerminalGame
from enro_terminal.llm_client import LlamaCppClient
from enro_terminal.nlu import QwenNlu
from enro_terminal.types import PersonaId


def main():
    client = LlamaCppClient()
    if not client.health():
        raise RuntimeError("Qwen hazır değil")
    game = TerminalGame(persona=PersonaId.NESELI, nlu=QwenNlu(client, seed=180),
                        actor=QwenPersonaActor(client, seed=180), executor=ProposalExecutor(),
                        clock=lambda: 0., timeout_seconds=86400.)
    session = CoopSession()
    session.connect(0)
    session.connect(1)
    session.confirm(0)
    session.confirm(1)
    fallback = 0
    for index, mission in enumerate(MISSIONS):
        session.pose(*mission.station, 0.)
        session.selection = session.order = index
        session.confirm(session.driver)
        epoch = session.begin_plan(session.coordinator)
        turn = game.process(f"Lütfen {mission.color.turkish} cismi ana masaya getir.")
        fallback += turn.used_actor_fallback
        # A real GUI receives pose updates concurrently during model inference.
        session.pose(*mission.station, 0.)
        assert turn.decision is not None, turn
        assert not turn.technical_error or turn.used_actor_fallback, turn
        assert session.accept_plan(epoch, turn.decision.actions, turn.reply), turn
        assert len(game.round_state.completed) == index
        assert not session.confirm(session.driver)
        assert session.confirm(session.coordinator)
        assert session.finish(epoch, True, "TEST ONLY: synthetic evidence, no ROS")
        game._apply_success(turn.decision.actions[0])
        print(f"PASS live Qwen {mission.color.value}; two distinct approvals; role swapped", flush=True)
    assert session.phase == Phase.WON
    print(f"COOP_LIVE_OK: 3/3; actor fallback={fallback}/3; physical actions=0", flush=True)


if __name__ == "__main__":
    main()
