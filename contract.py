# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
import datetime
import json
from genlayer import *

@gl.evm.contract_interface
class _Recipient:
    class View:
        pass
    class Write:
        pass

class PredictionPool(gl.Contract):
    opener_map: TreeMap[str, Address]
    description_map: TreeMap[str, str]
    source_url_map: TreeMap[str, str]
    deadline_map: TreeMap[str, str]
    abandon_deadline_map: TreeMap[str, str]
    status_map: TreeMap[str, str]
    outcome_map: TreeMap[str, str]
    yes_pool_map: TreeMap[str, u256]
    no_pool_map: TreeMap[str, u256]
    yes_count_map: TreeMap[str, u256]
    no_count_map: TreeMap[str, u256]
    topic_counter: u256

    stake_map: TreeMap[str, u256]
    stake_side_map: TreeMap[str, str]
    claimed_map: TreeMap[str, str]

    def __init__(self):
        self.topic_counter = u256(0)

    def _get_side(self, key: str) -> str:
        try:
            return self.stake_side_map[key]
        except Exception:
            return ""

    def _get_stake(self, key: str) -> u256:
        try:
            return self.stake_map[key]
        except Exception:
            return u256(0)

    def _get_claimed(self, key: str) -> str:
        try:
            return self.claimed_map[key]
        except Exception:
            return "no"

    @gl.public.write
    def open_topic(self, description: str, source_url: str, minutes_until_resolution: int) -> str:
        topic_id = f"T{self.topic_counter}"
        self.topic_counter += u256(1)

        self.opener_map[topic_id] = gl.message.sender_address
        self.description_map[topic_id] = description
        self.source_url_map[topic_id] = source_url
        self.deadline_map[topic_id] = str(datetime.datetime.now() + datetime.timedelta(minutes=minutes_until_resolution))
        self.abandon_deadline_map[topic_id] = str(datetime.datetime.now() + datetime.timedelta(minutes=minutes_until_resolution) + datetime.timedelta(days=30))
        self.status_map[topic_id] = "OPEN"
        self.outcome_map[topic_id] = ""
        self.yes_pool_map[topic_id] = u256(0)
        self.no_pool_map[topic_id] = u256(0)
        self.yes_count_map[topic_id] = u256(0)
        self.no_count_map[topic_id] = u256(0)

        return topic_id

    @gl.public.write.payable
    def stake_prediction(self, topic_id: str, side: str) -> None:
        assert self.status_map[topic_id] == "OPEN", "Topic not open"
        assert side in ("YES", "NO"), "Side must be YES or NO"
        assert str(datetime.datetime.now()) < self.deadline_map[topic_id], "Staking window has closed"
        assert gl.message.value > u256(0), "You must stake a positive amount"

        addr = str(gl.message.sender_address).lower()
        position_key = f"{topic_id}:{addr}"
        assert self._get_side(position_key) == "", "You already staked on this topic"

        stake_key = f"{topic_id}:{side}:{addr}"
        self.stake_map[stake_key] = gl.message.value
        self.stake_side_map[position_key] = side

        if side == "YES":
            self.yes_pool_map[topic_id] = self.yes_pool_map[topic_id] + gl.message.value
            self.yes_count_map[topic_id] = self.yes_count_map[topic_id] + u256(1)
        else:
            self.no_pool_map[topic_id] = self.no_pool_map[topic_id] + gl.message.value
            self.no_count_map[topic_id] = self.no_count_map[topic_id] + u256(1)

    @gl.public.write
    def cancel_topic(self, topic_id: str) -> None:
        assert gl.message.sender_address == self.opener_map[topic_id], "Only the opener can cancel"
        assert self.status_map[topic_id] == "OPEN", "Topic not open"
        assert self.yes_count_map[topic_id] == u256(0) and self.no_count_map[topic_id] == u256(0), "Cannot cancel after stakes have been placed"
        self.status_map[topic_id] = "CANCELLED"

    @gl.public.write
    def resolve_topic(self, topic_id: str) -> str:
        assert self.status_map[topic_id] == "OPEN", "Topic not open"
        assert str(datetime.datetime.now()) >= self.deadline_map[topic_id], "Resolution time has not arrived yet"

        description = self.description_map[topic_id]
        url = self.source_url_map[topic_id]

        def judge() -> str:
            content = gl.nondet.web.render(url, mode="text")
            prompt = f"""You are verifying the outcome of a prediction against real evidence.

Prediction being checked:
\"\"\"{description}\"\"\"

Fetched evidence content:
\"\"\"{content[:3000]}\"\"\"

Based strictly on the evidence, did the prediction come true?

Respond with strict JSON only, no markdown, no extra text:
{{"outcome": "YES", "reasoning": "<one sentence>"}}
or
{{"outcome": "NO", "reasoning": "<one sentence>"}}
"""
            return gl.nondet.exec_prompt(prompt)

        raw = gl.eq_principle.prompt_comparative(
            judge,
            "The outcome field must match exactly (YES or NO). Reasoning wording may vary but must express the same underlying judgment.",
        )

        try:
            parsed = json.loads(raw)
        except Exception:
            raise Exception("Resolver output was not valid JSON; refusing to resolve.")

        assert isinstance(parsed, dict), "Resolver output was not a JSON object; refusing to resolve."
        assert "outcome" in parsed, "Resolver output missing 'outcome' field; refusing to resolve."
        outcome = parsed["outcome"]
        assert isinstance(outcome, str), "Resolver 'outcome' field was not a string; refusing to resolve."
        assert outcome in ("YES", "NO"), "Resolver 'outcome' was outside the allowed domain; refusing to resolve."

        self.outcome_map[topic_id] = outcome
        self.status_map[topic_id] = "RESOLVED"

        return outcome

    @gl.public.write
    def claim_winnings(self, topic_id: str) -> str:
        assert self.status_map[topic_id] == "RESOLVED", "Topic not resolved yet"
        addr = str(gl.message.sender_address).lower()
        position_key = f"{topic_id}:{addr}"
        side = self._get_side(position_key)
        assert side != "", "You did not stake on this topic"
        assert self._get_claimed(position_key) == "no", "Already claimed"

        outcome = self.outcome_map[topic_id]
        stake_key = f"{topic_id}:{side}:{addr}"
        my_stake = self._get_stake(stake_key)

        assert side == outcome, "You staked on the losing side; nothing to claim."

        winning_pool = self.yes_pool_map[topic_id] if outcome == "YES" else self.no_pool_map[topic_id]
        losing_pool = self.no_pool_map[topic_id] if outcome == "YES" else self.yes_pool_map[topic_id]

        # Proportional (pari-mutuel) share: your bonus is the same fraction of the
        # losing pool as your stake is of the entire winning pool, not a flat
        # per-wallet split. winning_pool is always > 0 here since my_stake > 0
        # and my_stake is itself part of winning_pool.
        bonus = (losing_pool * my_stake) // winning_pool
        payout = my_stake + bonus

        self.claimed_map[position_key] = "yes"
        _Recipient(gl.message.sender_address).emit_transfer(value=payout)
        return "Claimed " + str(payout) + " wei"

    @gl.public.write
    def claim_abandoned_refund(self, topic_id: str) -> None:
        assert self.status_map[topic_id] in ("OPEN", "ABANDONED"), "Topic already resolved or cancelled"
        assert str(datetime.datetime.now()) >= self.abandon_deadline_map[topic_id], "Abandonment grace period hasn't passed"

        # The first refund claim atomically flips the topic to ABANDONED. From
        # that point on, resolve_topic and stake_prediction both require status
        # == "OPEN", so neither can run again — this topic can never be resolved
        # or staked into after any refund has been paid out, so claim_winnings
        # can never be computed against pool balances that refunds have already
        # drained.
        if self.status_map[topic_id] == "OPEN":
            self.status_map[topic_id] = "ABANDONED"

        addr = str(gl.message.sender_address).lower()
        position_key = f"{topic_id}:{addr}"
        side = self._get_side(position_key)
        assert side != "", "You did not stake on this topic"
        assert self._get_claimed(position_key) == "no", "Already claimed"

        stake_key = f"{topic_id}:{side}:{addr}"
        my_stake = self._get_stake(stake_key)
        self.claimed_map[position_key] = "yes"
        _Recipient(gl.message.sender_address).emit_transfer(value=my_stake)

    @gl.public.view
    def get_topic(self, topic_id: str) -> dict:
        return {
            "topic_id": topic_id,
            "opener": str(self.opener_map[topic_id]),
            "description": self.description_map[topic_id],
            "source_url": self.source_url_map[topic_id],
            "deadline": self.deadline_map[topic_id],
            "status": self.status_map[topic_id],
            "outcome": self.outcome_map[topic_id],
            "yes_pool": str(self.yes_pool_map[topic_id]),
            "no_pool": str(self.no_pool_map[topic_id]),
            "yes_count": str(self.yes_count_map[topic_id]),
            "no_count": str(self.no_count_map[topic_id]),
        }

    @gl.public.view
    def get_my_position(self, topic_id: str, address: str) -> dict:
        position_key = f"{topic_id}:{address.lower()}"
        side = self._get_side(position_key)
        stake_key = f"{topic_id}:{side}:{address.lower()}"
        return {
            "side": side if side != "" else "NONE",
            "stake": str(self._get_stake(stake_key)),
            "claimed": self._get_claimed(position_key),
        }

    @gl.public.view
    def get_topic_count(self) -> int:
        return int(self.topic_counter)
