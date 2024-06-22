- [中文](#受限的禁言)
- [English](#confined-timeout)

# 受限的全局禁言
允许特定成员或者身份组可以在服务器中禁言成员。然而其可以禁言的上限和间隔受到了限制。

## 实现
简短来说：
- 被指定的成员可以用菜单或者斜杠命令禁言某成员。
- 调解员需要被指定的管理员设置。
- 人们可以看见被禁言的成员以及其距离释放剩余的时间。
- 人们可以看到调解员都有谁。

### 存储数据库的数据结构
- GlobalAdmin: ID (INTEGER), Type (INTEGER)
- Moderator: ID (INTEGER), Type (INTEGER), ChannelID (INTEGER)
- Prisoner: ID (INTEGER), DateTimeRelease (DATETIME), ChannelID (INTEGER)
- Setting: Type (INTEGER), Setting (INTEGER), SETTING1 (STRING(100))

## 命令
- `/global_timeout setting limit <minute>`
- `/global_timeout setting step <minute>`
- `/global_timeout setting log_channel <channel>`
- `/global_timeout setting set_global_admin`
- `/global_timeout setting remove_global_admin [<user>] [<role>]`
- `/global_timeout setting view_global_admin`
- `/global_timeout setting set_moderator`
- `/global_timeout setting remove_moderator [<user>] [<role>]`
- `/global_timeout setting view_moderator`
- `/global_timeout setting summary`
- `/global_timeout timeout <Member> <Minutes>`
    - 用户菜单，弹窗输入信息。
    - 信息菜单，弹窗输入信息
- `/global_timeout release <Member>`
    - 用户菜单
- `/global_timeout view_prisoners`

# Confined Timeout
It allows certain members or roles able to timeout a member in the entire guild given there is a timeout upper limit and step size.

## Implementation
In contrast:
- The appointed members can timeout a certain member by either context menu and a slash command.
- The settings of the moderators will be set by the global admin.
- People can view the timed-out members with time left to be released.
- People can view the moderators.

### Persistent Data Structure for Database
- GlobalAdmin: ID (INTEGER), Type (INTEGER)
- Moderator: ID (INTEGER), Type (INTEGER), ChannelID (INTEGER)
- Prisoner: ID (INTEGER), DateTimeRelease (DATETIME), ChannelID (INTEGER)
- Setting: Type (INTEGER), Setting (INTEGER), SETTING1 (STRING(100))

## Commands
- `/global_timeout setting limit <minute>`
- `/global_timeout setting step <minute>`
- `/global_timeout setting log_channel <channel>`
- `/global_timeout setting set_global_admin`
- `/global_timeout setting remove_global_admin [<user>] [<role>]`
- `/global_timeout setting view_global_admin`
- `/global_timeout setting set_moderator`
- `/global_timeout setting remove_moderator [<user>] [<role>]`
- `/global_timeout setting view_moderator`
- `/global_timeout setting summary`
- `/global_timeout timeout <Member> <Minutes>`
    - User Context Menu, modal window to enter details
    - Message Context Menu, modal window to enter details. Message as the reason.
- `/global_timeout release <Member>`
    - User Context Menu
- `/global_timeout view_prisoners`