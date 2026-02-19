from __future__ import annotations

import discord
from discord import ui
from typing import List, Optional

class Paginator(ui.View):
    """Simple button paginator for a list of embeds."""

    def __init__(self, embeds: List[discord.Embed], author_id: int, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.author_id = author_id
        self.index = 0
        self._sync_buttons()

    def _sync_buttons(self):
        self.prev_btn.disabled = (self.index <= 0)
        self.next_btn.disabled = (self.index >= len(self.embeds) - 1)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message("Only the command invoker can use these buttons.", ephemeral=True)
        return False

    @ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: ui.Button):
        self.index = max(0, self.index - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: ui.Button):
        self.index = min(len(self.embeds) - 1, self.index + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    def first_embed(self) -> discord.Embed:
        return self.embeds[self.index]
