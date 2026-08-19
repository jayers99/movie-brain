Feature: My ratings
  Scenario Outline: Valid scores are stored
    Given a current film "Trio (1950)"
    When I rate it <score>
    Then its view shows my rating <score>
    Examples:
      | score |
      | 0     |
      | 7     |
      | 10    |

  Scenario: Blank un-rates
    Given a current film "Trio (1950)"
    When I rate it 7
    And I clear its rating
    Then its view shows no rating

  Scenario Outline: Out-of-range scores are rejected
    Given a current film "Trio (1950)"
    Then rating it <score> raises ValueError
    Examples:
      | score |
      | -1    |
      | 11    |

  Scenario: Unknown film is rejected
    Then rating film 999 raises LookupError
