import discord

class Theme:
    # embed colors
    INFO = 0x5DADE2
    OK = 0x2ECC71
    WARN = 0xF1C40F
    ERR = 0xE74C3C

    @staticmethod
    def medal_color(rank_name: str) -> int:
        rank = (rank_name or "").lower()
        # Knight/royal palette
        if rank in ("novice",):
            return 0x95A5A6  # gray
        if rank in ("squire",):
            return 0x3498DB  # blue
        if rank in ("knight",):
            return 0x2ECC71  # green
        if rank in ("baron", "count"):
            return 0x9B59B6  # purple
        if rank in ("duke",):
            return 0xF1C40F  # gold
        if rank in ("prince", "king", "emperor"):
            return 0xE67E22  # orange
        return Theme.INFO


def base_embed(title: str, description: str, color: int = Theme.INFO) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=color)
    e.set_footer(text="WordCounterBot")
    return e
