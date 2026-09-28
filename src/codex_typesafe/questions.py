FEATURE_NOUL_ID = "new_noul_1"

INSTRUCTION_TEMPLATE = (
    "Does the thread contain this feature: {feature}? Evaluate the thread in the state."
)


def feature_noul_questions(feature: str) -> dict:
    instructions = INSTRUCTION_TEMPLATE.replace("{feature}", feature)
    return {
        FEATURE_NOUL_ID: {
            "type": "noul",
            "instructions": instructions,
            "criteria": {
                "has_feature": "",
            },
        }
    }
