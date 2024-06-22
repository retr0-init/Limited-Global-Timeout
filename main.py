'''
Confined Timeout
Main entry point.
[WARNING] Modify the original library code: https://github.com/interactions-py/interactions.py/pull/1654

Copyright (C) 2024  __retr0.init__

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
'''
#WARNING Modify the original library code: https://github.com/interactions-py/interactions.py/pull/1654
import interactions
from interactions.ext.paginators import Paginator
from interactions.api.events import MemberAdd, MemberRemove
# Import the os module to get the parent path to the local files
import os
# aiofiles module is recommended for file operation
import aiofiles
import asyncio

import math

from enum import Enum, unique
from dataclasses import dataclass
import datetime
from typing import Union, cast, Callable, Awaitable, Optional, Self

import sqlalchemy
from sqlalchemy import select as sqlselect
from sqlalchemy import delete as sqldelete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, async_sessionmaker
import sqlalchemy.dialects.sqlite as sqlite

from .model import GlobalAdminDB, ModeratorDB, PrisonerDB, SettingDB, DBBase

engine: AsyncEngine = create_async_engine(f"sqlite+aiosqlite:///{os.path.dirname(__file__)}/confined_timeout_db.db")
Session = async_sessionmaker(engine)

@sqlalchemy.event.listens_for(engine.sync_engine, "connect")
def do_connect(dbapi_connection, connection_record):
    dbapi_connection.isolation_level = None

@sqlalchemy.event.listens_for(engine.sync_engine, "begin")
def do_begin(conn):
    conn.exec_driver_sql("BEGIN")

@unique
class MRCTType(int, Enum):
    USER = 1
    ROLE = 2

@unique
class SettingType(int, Enum):
    LOG_CHANNEL = 0
    MINUTE_LIMIT = 1
    MINUTE_STEP = 2

@dataclass
class GlobalAdmin:
    '''Global Admin Data Class'''
    __slots__ = ('id', 'type')
    id: int
    type: int

@dataclass
class GlobalModerator:
    '''Global Moderator Data Class'''
    __slots__ = ('id', 'type')
    id: int
    type: int

@dataclass
class Prisoner:
    '''Prinsoner Data Class'''
    __slots__ = ('id', 'release_datetime')
    id: int
    release_datetime: datetime.datetime
    def to_tuple(self) -> tuple:
        return (self.id)

@dataclass
class Config:
    '''Configuration Data Class'''
    __slots__ = ('type', 'setting','setting1')
    type: SettingType
    setting: int
    setting1: Optional[str]
    def upsert(self, setting_list: list[Self]) -> None:
        added: bool = False
        for i, conf in enumerate(setting_list):
            if self.type == conf.type:
                setting_list[i] = self
                added = True
                break
        if not added:
            setting_list.append(self)
        # Sort the list according to setting type
        __class__.sortList(setting_list)

    @staticmethod
    def sortList(setting_list: list[Self]) -> None:
        setting_list.sort(key=lambda a:a.type)

GLOBAL_ADMIN_USER_CUSTOM_ID: str = "retr0init_limited_global_timeout_GlobalAdmin_user"
GLOBAL_ADMIN_ROLE_CUSTOM_ID: str = "retr0init_limited_global_timeout_GlobalAdmin_role"
GLOBAL_MODERATOR_USER_CUSTOM_ID: str = "retr0init_limited_global_timeout_GlobalModerator_user"
GLOBAL_MODERATOR_ROLE_CUSTOM_ID: str = "retr0init_limited_global_timeout_GlobalModerator_role"
TIMEOUT_DIALOG_CUSTOM_ID: str = "retr0init_limited_global_timeout_TimeoutDialog"

global_admins: list[GlobalAdmin] = []
global_moderators: list[GlobalModerator] = []
prisoners: list[Prisoner] = []
prisoner_tasks: dict[tuple[int], asyncio.Task] = {}
global_settings: list[Config] = []

async def my_admin_check(ctx: interactions.BaseContext) -> bool:
    '''
    Check whether the person has the global admin permission to run the command
    '''
    res: bool = await interactions.is_owner()(ctx)
    gadmin_user: GlobalAdmin = GlobalAdmin(ctx.author.id, MRCTType.USER)
    res_user: bool = gadmin_user in global_admins
    res_role: bool = any(map(lambda x: ctx.author.has_role(x.id) and isinstance(x, GlobalAdmin) if x.type == MRCTType.ROLE else False, global_admins))

    return res or res_user or res_role

async def my_global_moderator_check(ctx: interactions.BaseContext) -> bool:
    '''
    Check whether the member has the channel moderator permission to run the command
    '''
    cmod_user: GlobalModerator = GlobalModerator(
        ctx.author.id,
        MRCTType.USER,
    )
    res_user: bool = cmod_user in global_moderators
    res_role: bool = any(map(
        lambda x: ctx.author.has_role(x.id) and isinstance(x, GlobalModerator) if x.type == MRCTType.ROLE else False,
        global_moderators
    ))
    return res_user or res_role

async def mycheck_or(*check_funcs: Callable[..., Awaitable[bool]]) -> Callable[..., Awaitable[bool]]:
    async def func(ctx: interactions.BaseContext) -> bool:
        for check_func in check_funcs:
            if await check_func(ctx):
                return True
        return False

    return func

async def mycheck_and(*check_funcs: Callable[..., Awaitable[bool]]) -> Callable[..., Awaitable[bool]]:
    async def func(ctx: interactions.BaseContext) -> bool:
        for check_func in check_funcs:
            if not await check_func(ctx):
                return False
        return True

    return func

'''
Confined Timeout Module
'''
class ModuleRetr0initLimitedGlobalTimeout(interactions.Extension):
    module_base: interactions.SlashCommand = interactions.SlashCommand(
        name="global_timeout",
        description="Global Limited timeout"
    )
    module_group_setting: interactions.SlashCommand = module_base.group(
        name="setting",
        description="Settings of the Confined Timeout system"
    )
    # Record async_start status to prevent duplicated start
    startup_flag: bool = False
    # asyncio locks
    lock_db: asyncio.Lock = asyncio.Lock()
    # minute autocomplete choices
    minute_choices: list[int] = []

    ################ Initial functions STARTS ################

    def __init__(self, bot):
        asyncio.create_task(self.async_init())

    async def async_init(self) -> None:
        '''Read all data into local list'''
        global global_admins
        global global_moderators
        global prisoners
        async with engine.begin() as conn:
            await conn.run_sync(DBBase.metadata.create_all)
        async with Session() as conn:
            gas = await conn.execute(sqlselect(GlobalAdminDB))
            cms = await conn.execute(sqlselect(ModeratorDB))
            ps  = await conn.execute(sqlselect(PrisonerDB))
            gss = await conn.execute(sqlselect(SettingDB))
        global_admins = [GlobalAdmin(ga[0].id, ga[0].type) for ga in gas]
        global_moderators = [GlobalModerator(cm[0].id, cm[0].type) for cm in cms]
        prisoners = [Prisoner(p[0].id, p[0].release_datetime) for p in ps]
        for _ in SettingType:
            Config(_, 600, None).upsert(global_settings)
        for gs in gss:
            Config(gs[0].type, gs[0].setting, gs[0].setting1).upsert(global_settings)
        await self.async_start()
        self.minute_choices = [i * global_settings[SettingType.MINUTE_STEP].setting for i in range(1, global_settings[SettingType.MINUTE_LIMIT].setting // global_settings[SettingType.MINUTE_STEP].setting + 1)]

    async def async_start(self) -> None:
        if self.startup_flag:
            return
        self.startup_flag = True
        await self.bot.wait_until_ready()
        cdt: datetime.datetime = datetime.datetime.now()
        for p in prisoners:
            duration_minutes: int = (p.release_datetime.replace(tzinfo=None) - cdt).total_seconds() / 60
            if duration_minutes <= 0:
                # Release the prinsoner
                await self.release_prinsoner(p)
            else:
                task = asyncio.create_task(self.release_prisoner_task(duration_minutes=duration_minutes, prisoner=p))
                prisoner_tasks[p.to_tuple()] = task
                task.add_done_callback(lambda x:prisoner_tasks.pop(p.to_tuple()))
    
    def drop(self):
        asyncio.create_task(self.async_drop())
        for i, task in prisoner_tasks.items():
            task.cancel()
        prisoner_tasks.clear()
        super().drop()
    
    async def async_drop(self):
        '''
        Dispose the Database Engine connection
        '''
        await engine.dispose()

    ################ Initial functions FINISH ################
    ##########################################################
    ################ Utility functions STARTS ################

    async def update_global_setting(self, confType: SettingType, setting: int, setting1: Optional[str] = None) -> None:
        assert isinstance(confType, int)
        assert isinstance(setting, int)
        conf: Config = Config(confType, setting, setting1)
        conf.upsert(global_settings)
        to_insert: dict = {"type": confType, "setting": setting}
        if setting1 is not None:
            assert isinstance(setting1, str)
            to_insert["setting1"] = setting1
        async with self.lock_db:
            async with Session() as session:
                stmt = sqlite.insert(SettingDB).values(
                    [to_insert]
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements = ['type'],
                    set_ = dict(
                        setting = stmt.excluded.setting,
                        setting1 = stmt.excluded.setting1
                    )
                )
                await session.execute(stmt)
                await session.commit()

    async def release_prinsoner(self, prisoner: Prisoner, ctx: interactions.BaseContext = None) -> None:
        if not any(i.id == prisoner.id for i in prisoners):
            if ctx is not None:
                await ctx.send("This member is not prisoned!", ephemeral=True)
            return
        user: interactions.Member = await self.bot.fetch_member(prisoner.id, self.bot.guilds[0])
        try:
            await user.timeout(None, "Limited Global Timeout Release prisoner")
        except interactions.errors.Forbidden:
            print("The bot needs to have enough permissions!")
            if ctx is not None:
                await ctx.send("The bot needs to have enough permissions! Please contact technical support!", ephemeral=True)
            return
        for p in prisoners:
            if p.id == prisoner.id:
                prisoners.remove(p)
                break
        async with self.lock_db:
            async with Session() as session:
                await session.execute(
                    sqldelete(PrisonerDB).
                    where(
                        PrisonerDB.id == prisoner.id
                    )
                )
                await session.commit()
        if ctx is not None:
            msg: str = f"The prisoner {ctx.guild.get_member(prisoner.id).mention} is released!"
            await ctx.send(embed=interactions.Embed(
                title="Limited Global Timeout", description=msg, color=int("80FF00", 16)))
            await self.send_log_channel(msg, int("80FF00", 16))
        else:
            if global_settings[SettingType.LOG_CHANNEL].setting1 is not None:
                g: interactions.Guild = self.bot.get_guild(int(global_settings[SettingType.LOG_CHANNEL].setting1))
                msg: str = f"The prisoner {g.get_member(prisoner.id).mention} is released!"
                await self.send_log_channel(msg, int("80FF00", 16))

    def check_prisoner(self, prisoner_member: interactions.Member, duration_minutes: int) -> tuple[bool, Prisoner]:
        prisoner: Prisoner = Prisoner(prisoner_member.id, datetime.datetime.now() + datetime.timedelta(minutes=duration_minutes))
        cp: list[Prisoner] = [p for p in prisoners if p.id == prisoner.id]
        return len(cp) > 0, prisoner

    async def jail_prisoner(self, prisoner_member: interactions.Member, duration_minutes: int, ctx: interactions.SlashContext = None, reason: str = "") -> bool:
        # Do not double jail existing prisoners
        existed, prisoner = self.check_prisoner(prisoner_member, duration_minutes)
        if existed:
            if ctx is not None:
                await ctx.send("The prisoner is already prisoned!", ephemeral=True)
            return False

        # Do not jail global moderators themselves
        cmod_user: GlobalModerator = GlobalModerator(
            prisoner_member.id,
            MRCTType.USER
        )
        res_user: bool = cmod_user in global_moderators
        res_role: bool = any(map(
            lambda x: prisoner_member.has_role(x.id) if x.type == MRCTType.ROLE else False,
            global_moderators
        ))
        if res_user or res_role:
            if ctx is not None:
                await ctx.send("You cannot jail moderator!", ephemeral=True)
            return False

        # Do not jail global admin themselves
        gadmin_user: GlobalAdmin = GlobalAdmin(
            prisoner_member.id,
            MRCTType.USER
        )
        res_user: bool = gadmin_user in global_admins
        res_role: bool = any(map(
            lambda x: prisoner_member.has_role(x.id) if x.type == MRCTType.ROLE else False,
            global_admins
        ))
        if res_user or res_role:
            if ctx is not None:
                await ctx.send("You cannot jail global admin!", ephemeral=True)
            return False

        # Test whether the jail duration is above the upper limit
        minute_limit: int = global_settings[SettingType.MINUTE_LIMIT].setting
        if duration_minutes > minute_limit:
            duration_minutes = minute_limit
            # if ctx is not None:
            #     await ctx.send(f"You cannot jail a member over {minute_limit} minutes!", ephemeral=True)
            # return False

        # Timeout a member
        try:
            await prisoner_member.timeout(
                prisoner.release_datetime,
                reason=f"Member {prisoner_member.display_name}({prisoner_member.id}) timeout for {duration_minutes} minutes in all channels. Reason:{reason[:50] if len(reason) > 51 else reason}")
        except interactions.errors.Forbidden:
            print("The bot needs to have enough permissions!")
            if ctx is not None:
                await ctx.send("The bot needs to have enough permissions! Please contact technical support!", ephemeral=True)
            return False
        prisoners.append(prisoner)
        async with self.lock_db:
            async with Session() as session:
                session.add(PrisonerDB(
                    id = prisoner.id,
                    release_datetime = prisoner.release_datetime
                ))
                await session.commit()
        if ctx is not None:
            await ctx.send(f"{prisoner_member.mention} is jailed for {duration_minutes} minutes in all channels. Reason: {'None' if len(reason) == 0 else reason[:50]+'...' if len(reason) > 51 else reason}", silent=True)
        else:
            await channel.send(f"{prisoner_member.mention} is jailed for {duration_minutes} minutes in all channels. Reason: {'None' if len(reason) == 0 else reason[:50]+'...' if len(reason) > 51 else reason}", silent=True)
        await self.send_log_channel(f"{prisoner_member.mention} is jailed for {duration_minutes} minutes in all channels. Reason: {'None' if len(reason) == 0 else reason[:50]+'...' if len(reason) > 51 else reason}", int("FFFF80", 16))
        # Wait for a certain number of time and unblock the member
        task = asyncio.create_task(self.release_prisoner_task(duration_minutes=duration_minutes, prisoner=prisoner, ctx=ctx))
        prisoner_tasks[prisoner.to_tuple()] = task
        task.add_done_callback(lambda x:prisoner_tasks.pop(prisoner.to_tuple()))
        return True

    async def release_prisoner_task(self, duration_minutes: int, prisoner: Prisoner, ctx: interactions.BaseContext = None) -> None:
        try:
            await asyncio.sleep(duration_minutes * 60.0)
            await self.release_prinsoner(prisoner=prisoner)
            user: interactions.Member = ctx.guild.get_member(prisoner.id)
            if ctx is not None:
                await ctx.channel.send(f"{user.mention} is released!", silent=True)
        except asyncio.CancelledError:
            pass

    async def send_log_channel(self, message: str, colour: int = 0) -> None:
        channel_config: Config = global_settings[SettingType.LOG_CHANNEL]
        if channel_config.setting1 is None:
            return
        guild: interactions.Guild = await self.bot.fetch_guild(int(channel_config.setting1))
        channel: interactions.MessageableMixin = await guild.fetch_channel(channel_config.setting)
        await channel.send(embed=interactions.Embed(
            title="Limited Global Timeout",
            description=message,
            color=colour,
            timestamp=interactions.Timestamp.now()
        ))
        pass

    ################ Utility functions FINISH ################

    ##########################################################

    ################ Eventsl functions STARTS ################

    @interactions.listen(MemberAdd)
    async def __event_memberadd(self, event: MemberAdd) -> None:
        """
        Re-jail the prisoners who left the guild
        """
        cdt: datetime.datetime = datetime.datetime.now()
        cps: list[Prisoner] = [p for p in prisoners if p.id == event.member.id]
        for cp in cps:
            duration_minutes: int = (cp.release_datetime.replace(tzinfo=None) - cdt).total_seconds() / 60
            duration_minutes = math.ceil(duration_minutes) if duration_minutes > 0 else 1
            channel: interactions.GuildChannel = await event.guild.fetch_channel(cp.channel_id)
            await self.release_prinsoner(cp)
            await self.jail_prisoner(event.member, duration_minutes, channel, reason="Re-jail escaped member")

    ################ Eventsl functions STARTS ################

    ##########################################################

    ################ Command functions STARTS ################

    @module_group_setting.subcommand("limit", sub_cmd_description="Set the minute timeout limitation")
    @interactions.slash_option(
        name = "minute",
        description = "The timeout limit",
        required = True,
        opt_type = interactions.OptionType.INTEGER,
        min_value=1
    )
    @interactions.check(my_admin_check)
    async def module_group_setting_setLimit(self, ctx: interactions.SlashContext, minute: int) -> None:
        """
        Set the upper limit of timeout duration in minutes
        """
        if minute <= 0:
            await ctx.send("The minute limit cannot be less than or equal to 0!", ephemeral=True)
            return
        step_minute: int = global_settings[SettingType.MINUTE_STEP].setting
        if minute < step_minute:
            await ctx.send(f"The limit cannot be less than the minute step `{step_minute} minutes`!", ephemeral=True)
            return
        await self.update_global_setting(SettingType.MINUTE_LIMIT, minute)
        self.minute_choices = [i * global_settings[SettingType.MINUTE_STEP].setting for i in range(1, global_settings[SettingType.MINUTE_LIMIT].setting // global_settings[SettingType.MINUTE_STEP].setting + 1)]
        await ctx.send(f"Timeout Upper Limit is {minute} minutes!")
        await self.send_log_channel(f"Timeout Upper Limit is {minute} minutes!")

    @module_group_setting.subcommand("step", sub_cmd_description="Set the minute timeout step")
    @interactions.slash_option(
        name = "minute",
        description = "The timeout step",
        required = True,
        opt_type = interactions.OptionType.INTEGER,
        min_value=1
    )
    @interactions.check(my_admin_check)
    async def module_group_setting_setStep(self, ctx: interactions.SlashContext, minute: int) -> None:
        """
        Set the step of timeout duration in minutes
        """
        if minute <= 0:
            await ctx.send("The minute step cannot be less than or equal to 0!", ephemeral=True)
            return
        limit_minute: int = global_settings[SettingType.MINUTE_LIMIT].setting
        if minute > limit_minute:
            await ctx.send(f"The step cannot be greater than the minute limit `{limit_minute} minutes`!", ephemeral=True)
            return
        await self.update_global_setting(SettingType.MINUTE_STEP, minute)
        self.minute_choices = [i * global_settings[SettingType.MINUTE_STEP].setting for i in range(1, global_settings[SettingType.MINUTE_LIMIT].setting // global_settings[SettingType.MINUTE_STEP].setting + 1)]
        await ctx.send(f"Timeout step is {minute} minutes!")
        await self.send_log_channel(f"Timeout step is {minute} minutes!")

    @module_group_setting.subcommand("log_channel", sub_cmd_description="Set the channel to output log")
    @interactions.slash_option(
        name = "channel",
        description="The channel to output the logs",
        required = True,
        opt_type = interactions.OptionType.CHANNEL
    )
    @interactions.check(my_admin_check)
    async def module_group_setting_setLogChannel(self, ctx: interactions.SlashContext, channel: interactions.GuildChannel) -> None:
        """
        Set the channel to log the moduel actions
        """
        if not hasattr(channel, "send"):
            await ctx.send(f"Message cannot be sent in this channel {channel.mention}", ephemeral=True)
        await self.update_global_setting(SettingType.LOG_CHANNEL, channel.id, str(ctx.guild.id))
        await ctx.send(f"Log channel is set to {channel.mention}")
        await self.send_log_channel(f"Log channel is set to {channel.mention}")

    @module_group_setting.subcommand("set_global_admin", sub_cmd_description="Set the Global Admin")
    @interactions.slash_option(
        name = "set_type",
        description = "Type of the admin. Select one of the options.",
        required = True,
        opt_type = interactions.OptionType.INTEGER,
        choices = [
            interactions.SlashCommandChoice(name="User", value=MRCTType.USER),
            interactions.SlashCommandChoice(name="Role", value=MRCTType.ROLE)
        ]
    )
    @interactions.check(my_admin_check)
    async def module_group_setting_setGlobalAdmin(self, ctx: interactions.SlashContext, set_type: int) -> None:
        '''
        Pop a User/Role Select Menu ephemeral to choose. It will disappear once selected.
        It will check whether the user or role is capable of the admin
        '''
        match set_type:
            case MRCTType.USER:
                component_user: interactions.UserSelectMenu = interactions.UserSelectMenu(
                    custom_id=GLOBAL_ADMIN_USER_CUSTOM_ID,
                    placeholder="Select the user for global admin",
                    max_values=25,
                    default_values=[ctx.guild.get_member(_.id) for _ in global_admins if _.type == MRCTType.USER]
                )
                await ctx.send("Set the global admin USER:", components=[component_user], ephemeral=True)
            case MRCTType.ROLE:
                component_role: interactions.RoleSelectMenu = interactions.RoleSelectMenu(
                    custom_id=GLOBAL_ADMIN_ROLE_CUSTOM_ID,
                    placeholder="Select the role for global admin",
                    max_values=25,
                    default_values=[ctx.guild.get_role(_.id) for _ in global_admins if _.type == MRCTType.ROLE]
                )
                await ctx.send("Set the global admin ROLE:", components=[component_role], ephemeral=True)

    async def setGACM_component(self, ctx: interactions.ComponentContext, ga_cm: bool, gaType: MRCTType) -> None:
        """
        Component callback function
        ctx: ComponentContext   The component context
        ga_cm: bool             Whether is Global Admin (True) or Global Moderator (False)
        gaType: MRCTType        The type of setting
        """
        if await my_admin_check(ctx):
            message: interactions.Message = ctx.message
            msg_to_send: str = "Added "
            msg_to_send += "Global Admin " if ga_cm else "Global Moderator "
            msg_to_send += "as a user:" if gaType == MRCTType.USER else "as a role:"
            for value in ctx.values:
                if gaType == MRCTType.USER:
                    value = cast(interactions.Member, value)
                    if value.bot:
                        continue
                elif gaType == MRCTType.ROLE:
                    value = cast(interactions.Role, value)
                if ga_cm:
                    _to_add: GlobalAdmin = GlobalAdmin(value.id, gaType)
                    if _to_add not in global_admins:
                        global_admins.append(_to_add)
                        async with self.lock_db:
                            async with Session() as conn:
                                conn.add(
                                    GlobalAdminDB(id=_to_add.id, type=_to_add.type)
                                )
                                await conn.commit()
                        msg_to_send += f"\n- {value.display_name if gaType == MRCTType.USER else value.name} {value.mention}"
                else:
                    _to_add: GlobalModerator = GlobalModerator(value.id, gaType)
                    if _to_add not in global_moderators:
                        global_moderators.append(_to_add)
                        async with self.lock_db:
                            async with Session() as conn:
                                conn.add(
                                    ModeratorDB(id=_to_add.id, type=_to_add.type)
                                )
                                await conn.commit()
                        msg_to_send += f"\n- {value.display_name if gaType == MRCTType.USER else value.name} {value.mention}"
            # Edit the original ephemeral message to hide the select menu
            await ctx.edit_origin(
                content=f"{'Global Admin' if ga_cm else 'Global Moderator'} {'user' if gaType == MRCTType.USER else 'role'} set!",
                components=[])
            # The edit above already acknowledged the context so has to send message to channel directly
            await self.send_log_channel(msg_to_send, int("0080FF", 16))
            return
        await ctx.send("You do not have the permission to do so!", ephemeral=True)
        pass

    @interactions.component_callback(GLOBAL_ADMIN_USER_CUSTOM_ID)
    async def callback_setGA_component_user(self, ctx: interactions.ComponentContext) -> None:
        await self.setGACM_component(ctx, True, MRCTType.USER)

    @interactions.component_callback(GLOBAL_ADMIN_ROLE_CUSTOM_ID)
    async def callback_setGA_component_role(self, ctx: interactions.ComponentContext) -> None:
        await self.setGACM_component(ctx, True, MRCTType.ROLE)


    @module_group_setting.subcommand("set_moderator", sub_cmd_description="Set the moderator in this channel")
    @interactions.slash_option(
        name = "set_type",
        description = "Type of the moderator. Select one of the options.",
        required = True,
        opt_type = interactions.OptionType.INTEGER,
        choices=[
            interactions.SlashCommandChoice(name="User", value=MRCTType.USER),
            interactions.SlashCommandChoice(name="Role", value=MRCTType.ROLE)
        ]
    )
    @interactions.check(my_admin_check)
    async def module_group_setting_setGlobalModerator(self, ctx: interactions.SlashContext, set_type: int) -> None:
        '''
        Pop a User/Role Select Menu ephemeral to choose. It will disappear once selected.
        It will check whether the user or role is capable of the moderator
        '''
        match set_type:
            case MRCTType.USER:
                component_user: interactions.UserSelectMenu = interactions.UserSelectMenu(
                    custom_id=GLOBAL_MODERATOR_USER_CUSTOM_ID,
                    placeholder=f"Select the user moderator",
                    max_values=25,
                    default_values=[ctx.guild.get_member(_.id) for _ in global_moderators if _.type == MRCTType.USER]
                )
                await ctx.send(f"Set the moderator USER:", components=[component_user], ephemeral=True)
            case MRCTType.ROLE:
                component_role: interactions.RoleSelectMenu = interactions.RoleSelectMenu(
                    custom_id=GLOBAL_MODERATOR_ROLE_CUSTOM_ID,
                    placeholder=f"Select the role moderator",
                    max_values=25,
                    default_values=[ctx.guild.get_role(_.id) for _ in global_moderators if _.type == MRCTType.ROLE]
                )
                await ctx.send("Set the moderator ROLE:", components=[component_role], ephemeral=True)

    @interactions.component_callback(GLOBAL_MODERATOR_USER_CUSTOM_ID)
    async def callback_setCM_component_user(self, ctx: interactions.ComponentContext) -> None:
        await self.setGACM_component(ctx, False, MRCTType.USER)

    @interactions.component_callback(GLOBAL_MODERATOR_ROLE_CUSTOM_ID)
    async def callback_setCM_component_role(self, ctx: interactions.ComponentContext) -> None:
        await self.setGACM_component(ctx, False, MRCTType.ROLE)

    @module_group_setting.subcommand("remove_global_admin", sub_cmd_description="Remove the Global Admin")
    @interactions.slash_option(
        "user",
        description="The global admin user to be removed",
        required=False,
        opt_type=interactions.OptionType.STRING,
        autocomplete=True
    )
    @interactions.slash_option(
        "role",
        description="The global admin role to be removed.",
        required=False,
        opt_type=interactions.OptionType.STRING,
        autocomplete=True
    )
    @interactions.check(my_admin_check)
    async def module_group_setting_removeGlobalAdmin(
        self, ctx: interactions.SlashContext,
        user: Optional[str] = None,
        role: Optional[str] = None) -> None:
        """
        Remove the global admin user or role
        """
        # If there is no parameter provided
        if user is None and role is None:
            await ctx.send("Please select either a user or a role to be removed!", ephemeral=True)
            return
        try:
            # Discord cannot transfer big integer so using string and convert to integer instead
            user = int(user) if user is not None else None
            role = int(role) if role is not None else None
        except ValueError:
            await ctx.send("Input value error! Please contact technical support.", ephemeral=True)
            return
        async with self.lock_db:
            async with Session() as session:
                msg: str = ""
                if user is not None:
                    ga: GlobalAdmin = GlobalAdmin(user, MRCTType.USER)
                    ga_mention: str = ctx.guild.get_member(ga.id).mention
                    if ga not in global_admins:
                        await ctx.send(f"{ga_mention} is not a global admin user!", silent=True)
                        return
                    msg += f"\n- {ga_mention}"
                    global_admins.remove(ga)
                    await session.execute(
                        sqldelete(GlobalAdminDB).
                        where(sqlalchemy.and_(
                            GlobalAdminDB.id == ga.id,
                            GlobalAdminDB.type == ga.type
                        ))
                    )
                if role is not None:
                    ga: GlobalAdmin = GlobalAdmin(role, MRCTType.ROLE)
                    ga_mention: str = ctx.guild.get_role(ga.id).mention
                    if ga not in global_admins:
                        await ctx.send(f"{ga_mention} is not a global admin role!", silent=True)
                        return
                    msg += f"\n- {ga_mention}"
                    global_admins.remove(ga)
                    await session.execute(
                        sqldelete(GlobalAdminDB).
                        where(sqlalchemy.and_(
                            GlobalAdminDB.id == ga.id,
                            GlobalAdminDB.type == ga.type
                        ))
                    )
                await session.commit()
        # Get user and role objects to get name and mention
        user: Optional[interactions.User] = ctx.guild.get_member(user) if user is not None else None
        role: Optional[interactions.Role] = ctx.guild.get_role(role) if role is not None else None
        await ctx.send(f"Removed global admins:\n{'- '+user.mention if user is not None else ''}\n{'- '+role.mention if role is not None else ''}")
        await self.send_log_channel(f"Removed global admins:\n{'- '+user.mention if user is not None else ''}\n{'- '+role.mention if role is not None else ''}", int("FF00FF", 16))
    
    @module_group_setting_removeGlobalAdmin.autocomplete("user")
    async def autocomplete_removeGlobalAdmin_user(self, ctx: interactions.AutocompleteContext) -> None:
        option_input: str = ctx.input_text
        options_user: list[interactions.Member] = [ctx.guild.get_member(i.id) for i in global_admins if i.type == MRCTType.USER]
        options_auto: list[interactions.Member] = [
            i for i in options_user if option_input in i.display_name or option_input in i.username
        ]
        await ctx.send(
            choices=[
                {
                    "name": i.display_name,
                    "value": str(i.id)
                } for i in options_auto
            ]
        )

    @module_group_setting_removeGlobalAdmin.autocomplete("role")
    async def autocomplete_removeGlobalAdmin_role(self, ctx: interactions.AutocompleteContext) -> None:
        option_input: str = ctx.input_text
        options_role: list[interactions.Role] = [ctx.guild.get_role(i.id) for i in global_admins if i.type == MRCTType.ROLE]
        options_auto: list[interactions.Role] = [
            i for i in options_role if option_input in i.name
        ]
        await ctx.send(
            choices=[
                {
                    "name": i.name,
                    "value": str(i.id)
                } for i in options_auto
            ]
        )
    
    @module_group_setting.subcommand("remove_global_mod", sub_cmd_description="Remove the Global Moderator")
    @interactions.slash_option(
        "user",
        description="The moderator user to be removed",
        required=False,
        opt_type=interactions.OptionType.STRING,
        autocomplete=True
    )
    @interactions.slash_option(
        "role",
        description="The moderator role to be removed.",
        required=False,
        opt_type=interactions.OptionType.STRING,
        autocomplete=True
    )
    @interactions.check(my_admin_check)
    async def module_group_setting_removeGlobalModerator(
        self, ctx: interactions.SlashContext,
        user: Optional[str] = None,
        role: Optional[str] = None) -> None:
        """
        Remove the moderator
        """
        # If there is no parameter provided
        if user is None and role is None:
            await ctx.send("Please select either a user or a role to be removed!", ephemeral=True)
            return
        try:
            # Discord cannot transfer big integer so using string and convert to integer instead
            user = int(user) if user is not None else None
            role = int(role) if role is not None else None
        except ValueError:
            await ctx.send("Input value error! Please contact technical support.", ephemeral=True)
            return
        async with self.lock_db:
            async with Session() as session:
                msg: str = ""
                if user is not None:
                    cm: GlobalModerator = GlobalModerator(user, MRCTType.USER)
                    cm_mention: str = ctx.guild.get_member(cm.id).mention
                    if cm not in global_moderators:
                        await ctx.send(f"{cm_mention} is not the moderator user!", silent=True)
                        return
                    msg += f"\n- {cm_mention}"
                    global_moderators.remove(cm)
                    await session.execute(
                        sqldelete(ModeratorDB).
                        where(sqlalchemy.and_(
                            ModeratorDB.id == cm.id,
                            ModeratorDB.type == cm.type
                        ))
                    )
                if role is not None:
                    cm: GlobalModerator = GlobalModerator(role, MRCTType.ROLE)
                    cm_mention: str = ctx.guild.get_role(cm.id).mention
                    if cm not in global_moderators:
                        await ctx.send(f"{cm_mention} is not the moderator role!", silent=True)
                        return
                    msg += f"\n- {cm_mention}"
                    global_moderators.remove(cm)
                    await session.execute(
                        sqldelete(ModeratorDB).
                        where(sqlalchemy.and_(
                            ModeratorDB.id == cm.id,
                            ModeratorDB.type == cm.type
                        ))
                    )
                await session.commit()
        # Get user and role objects to get name and mention
        user: Optional[interactions.User] = ctx.guild.get_member(user) if user is not None else None
        role: Optional[interactions.Role] = ctx.guild.get_role(role) if role is not None else None
        await ctx.send(f"Removed moderator in:\n{'- '+user.mention if user is not None else ''}\n{'- '+role.mention if role is not None else ''}")
        await self.send_log_channel(f"Removed moderator in:\n{'- '+user.mention if user is not None else ''}\n{'- '+role.mention if role is not None else ''}", int("FF80FF", 16))

    @module_group_setting_removeGlobalModerator.autocomplete("user")
    async def autocomplete_removeGlobalModerator_user(self, ctx: interactions.AutocompleteContext) -> None:
        option_input: str = ctx.input_text
        options_user: list[interactions.Member] = [ctx.guild.get_member(i.id) for i in global_moderators if i.type == MRCTType.USER]
        options_auto: list[interactions.Member] = [
            i for i in options_user if option_input in i.display_name or option_input in i.username
        ]
        await ctx.send(
            choices=[
                {
                    "name": i.display_name,
                    "value": str(i.id)
                } for i in options_auto
            ]
        )

    @module_group_setting_removeGlobalModerator.autocomplete("role")
    async def autocomplete_removeGlobalModerator_role(self, ctx: interactions.AutocompleteContext) -> None:
        option_input: str = ctx.input_text
        options_role: list[interactions.Role] = [ctx.guild.get_role(i.id) for i in global_moderators if i.type == MRCTType.ROLE]
        options_auto: list[interactions.Role] = [
            i for i in options_role if option_input in i.name
        ]
        await ctx.send(
            choices=[
                {
                    "name": i.name,
                    "value": str(i.id)
                } for i in options_auto
            ]
        )
    
    @module_group_setting.subcommand("view_global_admin", sub_cmd_description="View all Global Admins")
    async def module_group_setting_viewGlobalAdmin(self, ctx: interactions.SlashContext) -> None:
        msg: str = ""
        for i in global_admins:
            if i.type == MRCTType.USER:
                msg += f"- User: {ctx.guild.get_member(i.id).mention}\n"
            elif i.type == MRCTType.ROLE:
                role: interactions.Role = await ctx.guild.fetch_role(i.id)
                msg += f"- Role: {role.mention}\n"
                for u in role.members:
                    msg += f"  - User: {u.mention}\n"
        pag: Paginator = Paginator.create_from_string(self.bot, f"Global Admin for Confined Timeout:\n{msg}", page_size=1000)
        await pag.send(ctx)
    
    @module_group_setting.subcommand("view_global_mod", sub_cmd_description="View Moderators of this channel")
    async def module_group_setting_viewGlobalModerator(self, ctx: interactions.SlashContext) -> None:
        msg: str = ""
        for i in global_moderators:
            if i.channel_id != channel.id:
                continue
            if i.type == MRCTType.USER:
                msg += f"- User: {ctx.guild.get_member(i.id).mention}\n"
            elif i.type == MRCTType.ROLE:
                role: interactions.Role = await ctx.guild.fetch_role(i.id)
                msg += f"- Role: {role.mention}\n"
                for u in role.members:
                    msg += f"  - User: {u.mention}\n"
        pag: Paginator = Paginator.create_from_string(self.bot, f"Moderators for Limited Global Timeout:\n{msg}", page_size=1000)
        await pag.send(ctx)

    @module_base.subcommand("view_prisoners", sub_cmd_description="View Prisoners in this channel")
    async def module_base_view_prisoner(self, ctx: interactions.SlashContext) -> None:
        msg: str = f"Global Prisoners:\n" if len(prisoners) > 0 else f"No prisoners now."
        for i in prisoners:
            timeleft: datetime.timedelta = i.release_datetime.replace(tzinfo=None) - datetime.datetime.now()
            msg += f"- {ctx.guild.get_member(i.id).mention} `{timeleft.total_seconds() / 60:.2f} minutes left`\n"
        pag: Paginator = Paginator.create_from_string(self.bot, msg, page_size=2000, timeout=10)
        await pag.send(ctx)

    @module_group_setting.subcommand("summary", sub_cmd_description="View summary")
    async def module_group_setting_viewSummary(self, ctx: interactions.SlashContext) -> None:
        channel_config: Config = global_settings[SettingType.LOG_CHANNEL]
        minute_config: Config = global_settings[SettingType.MINUTE_LIMIT]
        step_config: Config = global_settings[SettingType.MINUTE_STEP]
        config_msg: str = "Log channel is "
        config_msg += "not set!" if str(ctx.guild.id) != channel_config.setting1 else ctx.guild.get_channel(int(channel_config.setting)).mention
        config_msg += f"\nTimeout Limit is `{minute_config.setting} minutes`\n"
        config_msg += f"\nTimeout Step is `{step_config.setting} minutes`\n"
        msg: str = config_msg + "\nGlobal Admins:\n"
        for i in global_admins:
            if i.type == MRCTType.USER:
                msg += f"- User: {ctx.guild.get_member(i.id).mention}\n"
            elif i.type == MRCTType.ROLE:
                role: interactions.Role = await ctx.guild.fetch_role(i.id)
                msg += f"- Role: {role.mention}\n"
                for u in role.members:
                    msg += f"  - User: {u.mention}\n"
        msg += f"\nModerator:\n"
        for i in global_moderators:
            if i.type == MRCTType.USER:
                msg += f"- User: {ctx.guild.get_member(i.id).mention}\n"
            elif i.type == MRCTType.ROLE:
                role: interactions.Role = await ctx.guild.fetch_role(i.id)
                msg += f"- Role: {role.mention}\n"
                for u in role.members:
                    msg += f"  - User: {u.mention}\n"
        msg += f"\nPrisoners:\n"
        for i in prisoners:
            timeleft: datetime.timedelta = i.release_datetime.replace(tzinfo=None) - datetime.datetime.now()
            timestring: str = f"{timeleft.total_seconds() / 60:.2f} minutes"
            msg += f"- {ctx.guild.get_member(i.id).mention} `{timestring} left`\n"
        pag: Paginator = Paginator.create_from_string(self.bot, f"Summary for Limited Global Timeout:\n\n{msg}", page_size=1000)
        await pag.send(ctx)
    
    @module_base.subcommand("timeout", sub_cmd_description="Timeout a member in this channel")
    @interactions.slash_option(
        "user",
        description="The user to timeout",
        required=True,
        opt_type=interactions.OptionType.USER
    )
    @interactions.slash_option(
        "minutes",
        description = "The minutes to timeout",
        required = True,
        opt_type=interactions.OptionType.INTEGER,
        autocomplete=True
    )
    @interactions.check(my_global_moderator_check)
    async def module_base_timeout(self, ctx: interactions.SlashContext, user: interactions.User, minutes: int) -> None:
        minutes = math.ceil(minutes / global_settings[SettingType.MINUTE_STEP].setting) * global_settings[SettingType.MINUTE_STEP].setting
        minutes = minutes if minutes <= global_settings[SettingType.MINUTE_LIMIT].setting else global_settings[SettingType.MINUTE_LIMIT].setting
        success: bool = await self.jail_prisoner(user, minutes, ctx=ctx)

    @module_base_timeout.autocomplete("minutes")
    async def autocomplete_timeout_minutes(self, ctx: interactions.AutocompleteContext) -> None:
        try:
            value: int = int(ctx.input_text)
        except ValueError:
            choices: list[int] = self.minute_choices
        else:
            choices: list[int] = [i for i in self.minute_choices if value <= i or str(value) in i]
        await ctx.send(
            choices=choices[:24]
        )
    
    async def cmd_timeout(self, ctx: interactions.ContextMenuContext, is_msg: bool):
        """
        Timeout function for context menu command usage
        ctx: ContextMenuContext Interactions Context Menu Context
        is_msg: bool            Whether this is used for message context menu
        """
        if is_msg:
            msg: interactions.Message = ctx.target
            user: interactions.Member = msg.author
        else:
            user: interactions.Member = ctx.target
        __t_func = lambda x, y: x if len(x) < y else f"{x[:y-3]}..."
        modal: interactions.Modal = interactions.Modal(
            interactions.ShortText(
                label="Minutes to timeout",
                placeholder=__t_func(f"Rounded every {global_settings[SettingType.MINUTE_STEP].setting} & Capped to {global_settings[SettingType.MINUTE_LIMIT].setting}", 99)),
            title=f"Globally Timeout {__t_func(user.display_name, 20)}"
        )
        await ctx.send_modal(modal=modal)
        modal_ctx: interactions.ModalContext = await ctx.bot.wait_for_modal(modal=modal)
        short_text: str = modal_ctx.responses[modal.components[0].custom_id]
        try:
            minutes: int = int(short_text)
        except ValueError:
            await modal_ctx.send("The input is not integer!", ephemeral=True)
            return
        minutes = round(minutes / global_settings[SettingType.MINUTE_STEP].setting) * global_settings[SettingType.MINUTE_STEP].setting
        minutes = minutes if minutes != 0 else global_settings[SettingType.MINUTE_STEP].setting
        success: bool = await self.jail_prisoner(user, minutes, ctx=sm_ctx.ctx, reason=msg.content if is_msg else "")

    @interactions.user_context_menu("Global Timeout User")
    @interactions.check(my_global_moderator_check)
    async def contextmenu_usr_timeout(self, ctx: interactions.ContextMenuContext) -> None:
        await self.cmd_timeout(ctx, is_msg=False)

    @interactions.message_context_menu("Global Timeout Msg")
    @interactions.check(my_global_moderator_check)
    async def contextmenu_msg_timeout(self, ctx: interactions.ContextMenuContext) -> None:
        await self.cmd_timeout(ctx, is_msg=True)
    
    async def cmd_release(
        self,
        ctx: Union[interactions.SlashContext, interactions.ContextMenuContext],
        is_cmd: bool,
        user: Optional[int] = None) -> None:
        """
        Release function for command usage
        ctx: Union[SlashContext, ContextMenuContext]    The interactions context
        is_cmd: bool                                    Whether this is used in command or context menu
        user: Optional[int]                             (Optional) The user id
        """
        if is_cmd:
            assert user is not None
            user: interactions.Member = await ctx.guild.fetch_member(user)
        else:
            user: interactions.Member = ctx.target
        prisoned, prisoner = self.check_prisoner(user, 1)
        if not prisoned:
            await ctx.send(f"The member {user.mention} is not prisoned!")
            return
        await self.release_prinsoner(prisoner=prisoner, ctx=ctx)
        if prisoner.to_tuple() in prisoner_tasks:
            prisoner_tasks[prisoner.to_tuple()].cancel()

    @module_base.subcommand("release", sub_cmd_description="Revoke a member timeout in this channel")
    @interactions.slash_option(
        "user",
        description="The user to release",
        required=True,
        opt_type=interactions.OptionType.STRING,
        autocomplete=True
    )
    @interactions.check(my_global_moderator_check)
    async def module_base_release(self, ctx: interactions.SlashContext, user: str) -> None:
        try:
            # Discord cannot transfer big integer so using string and convert to integer instead
            user = int(user) if user is not None else None
        except ValueError:
            await ctx.send("Input value error! Please contact technical support.", ephemeral=True)
            return
        await self.cmd_release(ctx, is_cmd=True, user=user)

    @module_base_release.autocomplete("user")
    async def autocomplete_release_user(self, ctx: interactions.AutocompleteContext) -> None:
        option_input: str = ctx.input_text
        options_user: list[interactions.Member] = [ctx.guild.get_member(i.id) for i in prisoners]
        options_auto: list[interactions.Member] = [
            i for i in options_user if option_input in i.display_name or option_input in i.username
        ]
        await ctx.send(
            choices=[
                {
                    "name": i.display_name,
                    "value": str(i.id)
                } for i in options_auto
            ]
        )
    
    @interactions.user_context_menu("Global Release")
    @interactions.check(my_global_moderator_check)
    async def contextmenu_usr_release(self, ctx: interactions.ContextMenuContext) -> None:
        await self.cmd_release(ctx, is_cmd=False, user=ctx.target.id)