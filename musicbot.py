import nextcord
from nextcord.ext import commands
import yt_dlp
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()  # .env 파일에 저장된 환경 변수 로드

intents = nextcord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

music_queue = []
music_titles = []  # 곡 제목을 저장할 리스트 추가

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)


class YTDLSource(nextcord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(nextcord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


@bot.slash_command(name="재생", description="주어진 URL 또는 검색어의 음악을 재생합니다.")
async def play(interaction: nextcord.Interaction, url: str):
    if not interaction.user.voice:
        await interaction.response.send_message("먼저 음성 채널에 입장해야 합니다.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    channel = interaction.user.voice.channel
    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)

    if not voice_client:
        voice_client = await channel.connect()

    # 음악을 재생하고 제목을 저장
    player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
    if player is None:
        await interaction.followup.send("음악을 재생할 수 없습니다. 유효한 URL인지 확인해 주세요.")
        return

    music_queue.append(url)
    music_titles.append(player.title)  # 제목 추가

    if voice_client.is_playing():
        await interaction.followup.send(f'곡이 큐에 추가되었습니다: {player.title}')
    else:
        # 현재 재생 중인 곡을 대기열에서 제거
        if music_queue:
            music_queue.pop(0)
            music_titles.pop(0)

        voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(interaction), bot.loop))
        await interaction.followup.send(f'재생 중: {player.title}')


async def play_next(interaction: nextcord.Interaction):
    if music_queue:
        next_song = music_queue.pop(0)
        title = music_titles.pop(0)  # 제목도 함께 제거
        player = await YTDLSource.from_url(next_song, loop=bot.loop, stream=True)
        if player:
            interaction.guild.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(interaction), bot.loop))
            await interaction.channel.send(f'다음 곡 재생 중: {title}')  # 제목 출력
        else:
            await interaction.channel.send("다음 곡을 재생할 수 없습니다.")


@bot.slash_command(name="스킵", description="현재 곡을 스킵하고 다음 곡을 재생합니다.")
async def skip(interaction: nextcord.Interaction):
    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)

    if not voice_client or not voice_client.is_playing():
        await interaction.response.send_message("현재 재생 중인 음악이 없습니다.")
        return

    # 현재 재생 중인 곡을 멈추고 다음 곡으로 넘어감
    voice_client.stop()
    await interaction.response.send_message("현재 곡을 스킵했습니다. 다음 곡을 재생합니다.")
    await play_next(interaction)


@bot.slash_command(name="대기열", description="대기열을 보여줍니다.")
async def queue(interaction: nextcord.Interaction):
    if not music_titles:  # 제목 리스트가 비어있다면
        await interaction.response.send_message("대기열이 비어있습니다.")
        return
    queue_list = "\n".join(f"{i + 1}. {title}" for i, title in enumerate(music_titles))  # 제목 출력
    await interaction.response.send_message(f"대기열:\n{queue_list}")


@bot.slash_command(name="대기열삭제", description="대기열에서 특정 번호의 곡을 삭제합니다.")
async def remove_from_queue(interaction: nextcord.Interaction, 번호: int):
    if 번호 < 1 or 번호 > len(music_titles):  # 제목 리스트의 길이로 체크
        await interaction.response.send_message("유효하지 않은 번호입니다.")
        return

    removed_song = music_titles.pop(번호 - 1)  # 제목 삭제
    music_queue.pop(번호 - 1)  # 원본 URL도 삭제
    await interaction.response.send_message(f"대기열에서 삭제된 곡: {removed_song}")


@bot.slash_command(name="끄기", description="음악을 멈추고 봇을 퇴장시킵니다.")
async def stop(interaction: nextcord.Interaction):
    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)

    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        await interaction.response.send_message("음악을 멈추고 봇이 퇴장했습니다.")
    else:
        await interaction.response.send_message("봇이 음성 채널에 있지 않습니다.")


@bot.event
async def on_ready():
    print(f'로그인 성공: {bot.user.name}')
    print('봇이 준비되었습니다.')  # 동기화 관련 코드는 제거


# .env 파일에서 토큰 로드
bot.run(os.getenv('DISCORD_TOKEN'))


# 커밋 테스트