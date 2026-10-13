from pathlib import Path
import tomllib

from .common import INACTIVE


class Scheduler:
    def __init__(self,root,profiles):
        self.profiles=profiles
        self.routing=tomllib.loads((Path(root)/"config/routing.toml").read_text())

    def mode(self,state):
        problems=state.rows("SELECT state,category FROM challenges")
        accepted=sum(p["state"]=="ACCEPTED_SELF" for p in problems)
        runnable=[p for p in problems if p["state"] not in INACTIVE]
        triaged=all(p["state"] not in {"NEW","PRESCANNED","INTAKE_DONE"} for p in runnable)
        return "depth" if accepted>=13 or len(runnable)<8 or triaged else "breadth"

    def next(self,task,value):
        r=self.routing
        category=value["classification"]["category"]
        security=category in r["security_categories"] or self.profiles[task["profile_id"]].daybreak
        stage=task["stage"]
        status=value["stage_status"]
        if status=="candidate":
            if not value["candidate_flag_ref"] or not value["reproduction_steps"]:
                raise ValueError("CANDIDATE_WITHOUT_REPRODUCTION")
            return r["verify_security" if security else "verify_general"],100,"CANDIDATE"
        if stage.startswith("verify"):
            if status=="verified":
                if not value["reproduction_steps"] or not value["evidence_delta"]:
                    raise ValueError("VERIFICATION_WITHOUT_EVIDENCE")
                return None,0,"VERIFIED"
            return r["security" if security else "general"],70,"SOLVING"
        if status=="verified":
            raise ValueError("ONLY_VERIFIER_CAN_VERIFY")
        if status in {"blocked","error"}:
            return None,0,"FROZEN"
        if stage=="intake":
            suggested=value["recommended_next_profile"]
            if category in r["quick_categories"] and value["classification"]["confidence"]>=r["quick_confidence"] and suggested==r["quick"]:
                return r["quick"],80,"INTAKE_DONE"
            return r["triage"],90,"INTAKE_DONE"
        if stage=="triage":
            if category=="unknown":
                return r["rescue"],45,"TRIAGED"
            return r["security" if security else "general"],60,"TRIAGED"
        if stage=="rescue":
            return r["security" if security else "general"],55,"SOLVING"
        if stage=="quick-solve":
            return r["security" if security else "general"],60,"SOLVING"
        if value["recommended_next_profile"]==r["rescue"]:
            return r["rescue"],40,"SOLVING"
        return r["security" if security else "general"],50,"SOLVING"
