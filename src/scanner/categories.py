"""Market category definitions and matching."""

import re
from enum import Enum
from typing import List, Optional

from src.models import Market


class CategoryMatcher:
    """
    Matches markets to predefined categories based on ticker patterns and metadata.
    """

    # Ticker patterns for each category
    # NOTE: Order matters — first matching category wins.
    # player_props must come before sports so basketball props aren't swallowed.
    CATEGORY_PATTERNS = {
        "college_basketball": [
            # NCAA Men's Basketball game outcomes (winner markets)
            r"^KXNCAAMBGAME",
            # NCAA Men's Basketball spreads
            r"^KXNCAAMBSPREAD",
            # NCAA Men's Basketball totals (over/under points)
            r"^KXNCAAMBTOTAL",
        ],
        "basketball": [
            # NCAA Men's Basketball
            r"^KXNCAAMBGAME",
            r"^KXNCAAMBSPREAD",
            r"^KXNCAAMBTOTAL",
            # NBA
            r"^KXNBAGAME",
            r"^KXNBASPREAD",
            r"^KXNBATOTAL",
            r"^KXNBA.*GAME",
        ],
        "player_props": [
            # Kalshi basketball ticker prefixes
            r"^KXNBA",
            r"^KXNCAAMB",
            # Basketball content in multivariate combo markets
            r"(?i)points\s+scored",
            r"(?i)wins\s+by\s+over.*[Pp]oints",
            r"(?i)\b(nba|ncaa\s*basketball)\b",
            r"(?i)basketball",
            r"(?i)all.star",
        ],
        "crypto": [
            r"(?i)btc",
            r"(?i)bitcoin",
            r"(?i)eth",
            r"(?i)ethereum",
            r"(?i)crypto",
            r"(?i)doge",
            r"(?i)sol",
            r"(?i)xrp",
        ],
        "weather": [
            r"(?i)weather",
            r"(?i)temperature",
            r"(?i)rain",
            r"(?i)snow",
            r"(?i)hurricane",
            r"(?i)storm",
            r"(?i)celsius",
            r"(?i)fahrenheit",
        ],
        "politics": [
            r"(?i)election",
            r"(?i)president",
            r"(?i)congress",
            r"(?i)senate",
            r"(?i)house",
            r"(?i)vote",
            r"(?i)poll",
            r"(?i)governor",
            r"(?i)democrat",
            r"(?i)republican",
            r"(?i)biden",
            r"(?i)trump",
        ],
        "economics": [
            r"(?i)fed",
            r"(?i)fomc",
            r"(?i)rate",
            r"(?i)inflation",
            r"(?i)cpi",
            r"(?i)gdp",
            r"(?i)jobs",
            r"(?i)unemployment",
            r"(?i)payroll",
            r"(?i)treasury",
        ],
        "sports": [
            r"(?i)nfl",
            r"(?i)nba",
            r"(?i)mlb",
            r"(?i)nhl",
            r"(?i)super\s*bowl",
            r"(?i)world\s*series",
            r"(?i)championship",
            r"(?i)playoffs",
            r"(?i)esports",
            r"(?i)table\s*tennis",
            r"(?i)points",
            r"(?i)rebounds",
            r"(?i)assists",
            r"(?i)win\s+map",
            r"(?i)winner",
            r"(?i)over\s+\d+",
            r"(?i)under\s+\d+",
            r"KXMV",  # Multivariate esports
            r"KXTABLETENNIS",
            r"KXCS2",  # CS2 esports
        ],
    }

    # Markets to exclude — mention markets, multivariate combos (parlays), etc.
    EXCLUDE_PATTERNS = [
        r"(?i)mention",
        r"(?i)tweet",
        r"(?i)post\s+about",
        r"(?i)social\s*media",
        r"(?i)say\s+.*\s+on",
        r"(?i)truth\s*social",
        r"^KXMV",  # Multivariate combo/parlay markets (not individual props)
    ]

    def __init__(self):
        """Compile regex patterns for efficiency."""
        self._compiled_patterns = {}
        for category, patterns in self.CATEGORY_PATTERNS.items():
            self._compiled_patterns[category] = [
                re.compile(p) for p in patterns
            ]
        self._compiled_excludes = [re.compile(p) for p in self.EXCLUDE_PATTERNS]

    def is_excluded(self, market: Market) -> bool:
        """
        Check if a market matches any exclusion pattern (e.g. mention markets).

        Args:
            market: Market to check

        Returns:
            True if the market should be excluded
        """
        text_to_check = f"{market.ticker} {market.title} {market.category}"
        for pattern in self._compiled_excludes:
            if pattern.search(text_to_check):
                return True
        return False

    def get_category(self, market: Market) -> Optional[str]:
        """
        Determine the category of a market.

        Args:
            market: Market to categorize

        Returns:
            Category name or None if no match
        """
        text_to_check = f"{market.ticker} {market.title} {market.category}"

        for category, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                if pattern.search(text_to_check):
                    return category

        return None

    def matches_category(self, market: Market, target_category: str) -> bool:
        """
        Check if a market matches a target category.

        Always excludes mention/social media markets regardless of category.

        Args:
            market: Market to check
            target_category: Category to match ('all' matches everything)

        Returns:
            True if market matches the category and is not excluded
        """
        # Always exclude mention markets
        if self.is_excluded(market):
            return False

        if target_category.lower() == "all":
            return True

        market_category = self.get_category(market)
        return market_category == target_category.lower()

    def get_all_categories(self) -> List[str]:
        """Get list of all supported categories."""
        return ["all"] + list(self.CATEGORY_PATTERNS.keys())


# Global category matcher instance
_category_matcher = CategoryMatcher()


def matches_category(market: Market, category: str) -> bool:
    """Convenience function to check category match."""
    return _category_matcher.matches_category(market, category)


def get_market_category(market: Market) -> Optional[str]:
    """Convenience function to get market category."""
    return _category_matcher.get_category(market)
