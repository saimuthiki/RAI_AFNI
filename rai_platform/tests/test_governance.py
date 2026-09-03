# -*- coding: utf-8 -*-
"""The governance register.

Build-plan item 21 asked AFNI for "one accountable owner per tenet - seven
names", and said no code could produce it. AFNI's answer was that the framework
comes with all of this, so why does it need names. They were right, and the
answer was a design change: ROLES are generated, and what a deployment supplies
is at most one setting.

These tests pin the three things that would make that design dishonest:

  * NO DOMAIN IS INVENTED. A plausible-looking escalation address that goes
    nowhere is worse in a compliance artefact than a visibly unfinished one.
  * THE REGISTER IS READ FROM THE LIVE PLATFORM. A register assembled from
    hardcoded numbers can describe a configuration nobody is running, which is
    the whole failure mode of a hand-maintained one.
  * A BROKEN GOVERNANCE SETTING IS NOT FATAL. A typo in an optional field must
    not stop a guardrail gateway booting.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from afni_rai import governance, sensitivity                     # noqa: E402
from afni_rai.contract.models import Tenet                       # noqa: E402
from afni_rai.tenets.accountability.thresholds import (          # noqa: E402
    ThresholdOverrides, ThresholdStore)

try:
    from fastapi.testclient import TestClient
    from afni_rai.gateway.app import create_app
    _HAVE_FASTAPI = True
except Exception:                                                # noqa: BLE001
    _HAVE_FASTAPI = False


def _env(case, **values):
    """Set environment variables for one test and restore them after."""
    before = {k: os.environ.get(k) for k in values}

    def restore():
        for key, was in before.items():
            if was is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = was
    case.addCleanup(restore)
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


class Roles(unittest.TestCase):

    def test_there_is_exactly_one_owner_per_tenet(self):
        _env(self, **{governance.ENV_DOMAIN: None,
                      governance.ENV_OWNERS: None})
        rows = governance.owners()
        self.assertEqual(len(rows), len(Tenet))
        self.assertEqual([o.tenet for o in rows], list(Tenet))

    def test_the_role_is_a_steward_not_an_owner(self):
        # "Owner" sounds like a person; "steward" is a role somebody holds,
        # which is what survives them changing team.
        for owner in governance.owners():
            with self.subTest(tenet=owner.tenet.value):
                self.assertIn("steward", owner.role)
                self.assertIn("AFNI", owner.role)

    def test_every_tenet_says_what_it_is_accountable_FOR(self):
        # "Owner of Privacy" is a label, not an accountability. An escalation
        # path has to say what arriving at it means.
        self.assertEqual(set(governance.ACCOUNTABLE_FOR), set(Tenet))
        for tenet, text in governance.ACCOUNTABLE_FOR.items():
            with self.subTest(tenet=tenet.value):
                self.assertGreater(len(text), 60)

    def test_every_tenet_has_a_distinct_alias(self):
        aliases = [governance.ALIAS[t] for t in Tenet]
        self.assertEqual(len(aliases), len(set(aliases)))

    def test_no_persons_name_appears_anywhere_in_the_module(self):
        # The design decision, asserted. If somebody adds a default name the
        # register goes stale silently, which is exactly what was argued against.
        import inspect
        source = inspect.getsource(governance)
        for forbidden in ("Kiran", "@gmail", "@outlook", "@yahoo"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)


class NoDomainIsInvented(unittest.TestCase):

    def test_without_the_env_var_the_contact_is_an_alias_with_no_domain(self):
        _env(self, **{governance.ENV_DOMAIN: None,
                      governance.ENV_OWNERS: None})
        for owner in governance.owners():
            with self.subTest(tenet=owner.tenet.value):
                self.assertNotIn("@", owner.contact)
                self.assertFalse(owner.resolved)

    def test_one_setting_arms_all_seven(self):
        _env(self, **{governance.ENV_DOMAIN: "afni.example",
                      governance.ENV_OWNERS: None})
        rows = governance.owners()
        self.assertTrue(all(o.resolved for o in rows))
        self.assertTrue(all(o.contact.endswith("@afni.example") for o in rows))

    def test_a_leading_at_in_the_domain_is_tolerated(self):
        _env(self, **{governance.ENV_DOMAIN: "@afni.example"})
        self.assertEqual(governance.domain(), "afni.example")

    def test_the_register_reports_the_gap_rather_than_hiding_it(self):
        _env(self, **{governance.ENV_DOMAIN: None,
                      governance.ENV_OWNERS: None})
        doc = governance.register()
        self.assertEqual(doc["counts"]["resolved"], 0)
        self.assertTrue(any(governance.ENV_DOMAIN in p for p in doc["problems"]))


class OneSharedMailbox(unittest.TestCase):
    """`AFNI_GOVERNANCE_CONTACT` — added because DOMAIN was the wrong tool.

    Asked for a domain, AFNI offered one real personal mailbox. Setting
    `AFNI_GOVERNANCE_DOMAIN` to that mailbox's domain would have generated
    `rai-privacy@…` and six siblings — **seven addresses that do not exist** —
    which is exactly the "plausible address that goes nowhere" this module
    argues is worse than an honest gap.
    """

    def test_one_address_serves_all_seven(self):
        _env(self, **{governance.ENV_CONTACT: "ops@afni.example",
                      governance.ENV_DOMAIN: None,
                      governance.ENV_OWNERS: None})
        rows = governance.owners()
        self.assertEqual({o.contact for o in rows}, {"ops@afni.example"})
        self.assertTrue(all(o.resolved for o in rows))
        self.assertTrue(all(o.source == "shared" for o in rows))

    def test_it_does_NOT_invent_seven_aliases_on_that_domain(self):
        # The whole reason this option exists.
        _env(self, **{governance.ENV_CONTACT: "ops@afni.example",
                      governance.ENV_DOMAIN: None,
                      governance.ENV_OWNERS: None})
        contacts = {o.contact for o in governance.owners()}
        for alias in governance.ALIAS.values():
            with self.subTest(alias=alias):
                self.assertNotIn(f"{alias}@afni.example", contacts)

    def test_the_weakness_is_reported_rather_than_treated_as_finished(self):
        # Reachable beats bouncing, but one inbox for seven tenets has no
        # routing. Saying so is the difference between a starting point and a
        # tick-box.
        _env(self, **{governance.ENV_CONTACT: "ops@afni.example",
                      governance.ENV_DOMAIN: None,
                      governance.ENV_OWNERS: None})
        doc = governance.register(rails=[])
        self.assertEqual(doc["counts"]["resolved"], 7)
        self.assertTrue(any("WEAKER governance" in p for p in doc["problems"]))

    def test_a_per_tenet_owner_still_wins(self):
        import json
        _env(self, **{governance.ENV_CONTACT: "ops@afni.example",
                      governance.ENV_DOMAIN: None,
                      governance.ENV_OWNERS: json.dumps(
                          {"Privacy": "dpo@afni.example"})})
        rows = {o.tenet: o for o in governance.owners()}
        self.assertEqual(rows[Tenet.PRIVACY].contact, "dpo@afni.example")
        self.assertEqual(rows[Tenet.SECURITY].contact, "ops@afni.example")

    def test_the_domain_option_is_still_there_and_loses_to_contact(self):
        _env(self, **{governance.ENV_CONTACT: "ops@afni.example",
                      governance.ENV_DOMAIN: "afni.example",
                      governance.ENV_OWNERS: None})
        self.assertEqual({o.contact for o in governance.owners()},
                         {"ops@afni.example"})


class ExplicitOwners(unittest.TestCase):

    def test_a_configured_owner_replaces_the_generated_one(self):
        _env(self, **{
            governance.ENV_DOMAIN: None,
            governance.ENV_OWNERS: json.dumps(
                {"Privacy": "dpo@afni.example"})})
        rows = {o.tenet: o for o in governance.owners()}
        self.assertEqual(rows[Tenet.PRIVACY].contact, "dpo@afni.example")
        self.assertEqual(rows[Tenet.PRIVACY].source, "configured")
        self.assertTrue(rows[Tenet.PRIVACY].resolved)
        # The rest stay generated.
        self.assertEqual(rows[Tenet.SECURITY].source, "generated")

    def test_an_unknown_tenet_name_is_ignored(self):
        _env(self, **{governance.ENV_OWNERS: json.dumps(
            {"Not A Tenet": "x@y.example"})})
        self.assertEqual(governance._configured(), {})

    def test_malformed_json_is_ignored_and_reported_not_fatal(self):
        _env(self, **{governance.ENV_DOMAIN: None,
                      governance.ENV_OWNERS: "{not json"})
        rows = governance.owners()
        self.assertTrue(all(o.source == "generated" for o in rows))
        problems = governance._owner_problems()
        self.assertTrue(any(governance.ENV_OWNERS in p for p in problems))
        self.assertTrue(any("IGNORED" in p for p in problems))


class TheRegisterIsLive(unittest.TestCase):

    def test_it_reads_the_thresholds_in_force_not_the_shipped_ones(self):
        store = ThresholdStore()
        store.put_overrides(ThresholdOverrides(
            thresholds={"safety.toxicity": 0.11}))
        doc = governance.register(rails=[], thresholds=store)
        row = next(r for r in doc["tenets"]
                   if r["tenet"] == Tenet.CONTENT_SAFETY.value)
        knob = next(k for k in row["thresholds"] if k["key"] == "safety.toxicity")
        self.assertEqual(knob["effective"], 0.11)
        self.assertNotEqual(knob["shipped"], 0.11)

    def test_every_sensitivity_knob_lands_under_exactly_one_tenet(self):
        mapped = governance._knobs_by_tenet()
        flat = [k for keys in mapped.values() for k in keys]
        self.assertEqual(sorted(flat), sorted(k.key for k in sensitivity.KNOBS))
        self.assertEqual(len(flat), len(set(flat)))

    def test_building_the_register_does_not_pollute_the_audit_read_log(self):
        # Only the detection path's threshold reads are evidence of anything.
        # Opening a governance page must not look like traffic.
        store = ThresholdStore()
        governance.register(rails=[], thresholds=store)
        self.assertEqual(store.reads, [])

    def test_rails_are_grouped_by_their_own_tenet(self):
        from afni_rai.cli import load_tenets
        rails, _attrs, _problems = load_tenets()
        doc = governance.register(rails=rails)
        total = sum(r["rails_mounted"] for r in doc["tenets"])
        self.assertEqual(total, len(rails),
                         "a rail counted under no tenet is a rail with no "
                         "accountable role")

    def test_the_markdown_renders_every_tenet_and_says_it_is_generated(self):
        doc = governance.register(rails=[], thresholds=ThresholdStore())
        text = governance.render(doc)
        self.assertIn("Generated from the running platform", text)
        for tenet in Tenet:
            with self.subTest(tenet=tenet.value):
                self.assertIn(f"## {tenet.value}", text)

    def test_the_fail_mode_is_reported_as_unconditional(self):
        doc = governance.register(rails=[], thresholds=ThresholdStore())
        self.assertIn("unconditional", doc["fail_mode"])
        self.assertIn("no request field", doc["fail_mode_note"])


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi is not installed")
class Endpoint(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(create_app())

    def test_it_returns_seven_roles(self):
        doc = self.client.get("/v1/governance").json()
        self.assertEqual(len(doc["tenets"]), len(Tenet))
        for row in doc["tenets"]:
            with self.subTest(tenet=row["tenet"]):
                self.assertIn("steward", row["role"])

    def test_it_explains_why_there_are_no_names(self):
        doc = self.client.get("/v1/governance").json()
        self.assertIn("Roles, not people", doc["why_no_names"])
        self.assertIn(governance.ENV_DOMAIN, doc["why_no_names"])

    def test_it_reports_the_rails_the_gateway_actually_mounted(self):
        doc = self.client.get("/v1/governance").json()
        gateway = self.client.app.state.gateway
        total = sum(r["rails_mounted"] for r in doc["tenets"])
        self.assertEqual(total, len(gateway.rails))

    def test_the_route_is_in_the_openapi_document(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertIn("/v1/governance", paths)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
