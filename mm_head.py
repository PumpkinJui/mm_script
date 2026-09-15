from argparse import ArgumentParser, Namespace
from base64 import urlsafe_b64decode as b64d
from csv import reader, writer
from json import dump, dumps, load, loads
from logging import (
    DEBUG,
    WARNING,
    FileHandler,
    Formatter,
    StreamHandler,
    getLogger,
    shutdown,
)
from pathlib import Path
from re import search, sub
from shutil import which
from subprocess import run
from time import sleep
from typing import Final, Literal, TypedDict, cast

from deepdiff import DeepDiff
from PIL import Image
from requests import exceptions, get


class ExtractedDictInfo(TypedDict):
    id: str
    location: str
    rotation: int | None
    facing: str | None
    url: str
    meaningful: bool
    armor_stand: bool


type DataDictInfo = dict[str, list[ExtractedDictInfo]]


class Get:
    POS: Final[str] = 'GET'

    @staticmethod
    def search_group(pattern: str, data: str) -> str:
        result = search(pattern, data)
        if not result:
            logger.error('不能从 %s 中获得 "%s"！', data, pattern, extra={'pos': 'GET'})
            raise AssertionError
        exact = result.group(1)
        assert isinstance(exact, str)
        return exact

    @staticmethod
    def get_name(data: str) -> tuple[str, str, bool]:
        name: str = ''
        url: str = ''
        meaningful: bool = True
        trans = str.maketrans(' -', '__', '().#')
        if 'value:' in data:
            b64_raw = Get.search_group(r'value: ?"([^\"]+)"', data)
            b64_raw += '=' * (-len(b64_raw) % 4)
            b64_decoded = b64d(b64_raw).decode()
            url = cast(str, loads(b64_decoded)['textures']['SKIN']['url']).replace(
                'http:', 'https:'
            )
            name_raw = search(r'(?:name|text): ?"([^"]*)"', data)
            if 'minecraft:custom_name' in data and 'text:' not in data:
                name_raw = search(
                    r'"minecraft:custom_name": ?"(?:§[a-z\d])?([^"]+)"', data
                )
            if not name_raw or name_raw.group(1) in {'', 'textures'}:
                name = url[url.rfind('/') + 1 : url.rfind('/') + 7]
                meaningful = False
            else:
                name = name_raw.group(1).translate(trans).lower()
        elif 'head:' in data:
            name = Get.search_group(r'head: ?\{[^}]*id: ?"([^"]+)"\}', data)
            name = name.translate(trans).lower()
        else:
            meaningful = False
        if meaningful and name and url:
            name += f'_{url[url.rfind("/") + 1 : url.rfind("/") + 3]}'
        assert isinstance(name, str)
        return name, url, meaningful

    def extract(self, data: str) -> ExtractedDictInfo | None:
        facing, rotation = None, None
        armor_stand = 'armor_stand' in data
        location = Get.search_group(r' ([\d\-. ]+) ', data)
        if '.' in location:
            location = [int(float(i)) for i in location.split(' ')]
            location[1] += 1
            location = ' '.join(map(str, location))
        if 'rotation' in data:
            rotation = int(Get.search_group(r'rotation=(\d+)', data))
        elif 'Rotation' in data:
            rotation_map = [180]
            rotation_map.extend(int(-157.5 + i * 22.5) for i in range(15))
            rotation_raw = Get.search_group(r'Rotation: ?\[([\d\-.]+)f', data)
            rotation_raw = '180.0' if rotation_raw == '-180.0' else rotation_raw
            rotation_closest = min(
                rotation_map, key=lambda x: abs(int(float(rotation_raw)) - x)
            )
            rotation = rotation_map.index(rotation_closest)
        elif 'facing' in data:
            facing = Get.search_group(r'facing=([^,\]]+)', data)
        name, url, meaningful = Get.get_name(data)
        if not (name or url or meaningful):
            print()
            logger.warning('无头颅数据。', extra={'pos': f'L{self.linum}'})
            return None
        print(name, end=' - ', flush=True)
        return {
            'id': name,
            'location': location,
            'rotation': rotation,
            'facing': facing,
            'url': url,
            'meaningful': meaningful,
            'armor_stand': armor_stand,
        }

    def downloading(self, url: str, name: str) -> bool:
        img_path = self.img_dir / f'{name}.png'
        if cast(bool, arg_parser().nodl) or not url or img_path.is_file():
            print('跳过下载...', end='', flush=True)
            if url and img_path.is_file() and Get.padding(img_path):
                print('成功！', flush=True)
            else:
                print()
            return False
        print('开始下载...', end='', flush=True)
        for i in range(3):
            try:
                response = get(url, timeout=(6.05, 10))
                response.raise_for_status()
                break
            except exceptions.ConnectionError:
                print(f'连接错误（{i + 1}/3）...', end='', flush=True)
                sleep(1)
            except exceptions.HTTPError as e:
                assert e.response is not None
                print(
                    f'状态码 {e.response.status_code}（{i + 1}/3）...',
                    end='',
                    flush=True,
                )
            except exceptions.Timeout:
                print(f'超时（{i + 1}/3）...', end='', flush=True)
                sleep(1)
        else:
            print()
            logger.error('已超时。', extra={'pos': f'L{self.linum} - {name}'})
            return False
        with open(img_path, 'wb') as f:
            _ = f.write(response.content)
        _ = Get.padding(img_path)
        print('成功！', flush=True)
        return True

    @staticmethod
    def padding(img_path: Path) -> bool:
        temp_path = img_path.with_name(img_path.name + '.tmp')
        with Image.open(img_path) as f:
            if f.size != (64, 32):
                return False
            print('转换中...', end='', flush=True)
            img = f.convert('RGBA')
            if 'thegreatergod' in str(img_path):
                print('thelesserdog...', end='', flush=True)
                pixel = img.load()
                assert pixel is not None
                for w in range(32, 64):
                    for h in range(16):
                        if pixel[w, h] == (255, 255, 255, 255):
                            pixel[w, h] = (0, 0, 0, 0)
            new_img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
            new_img.paste(img, (0, 0), img)
            new_img.save(temp_path, format='PNG')
        _ = temp_path.replace(img_path)
        return True

    def merge(
        self,
        dict_general: DataDictInfo,
        dict_entry: ExtractedDictInfo | None,
        stem: str,
    ) -> DataDictInfo:
        if not dict_entry:
            return dict_general
        name, url = dict_entry['id'], dict_entry['url']
        _ = self.downloading(url, name)
        if dict_general.get(stem):
            location2id = {i['location']: i['id'] for i in dict_general[stem]}
            if not (id_tocheck := location2id.get(dict_entry['location'])):
                dict_general[stem].append(dict_entry)
            else:
                logger.warning(
                    '位置 %s 已存在头颅 %s。',
                    dict_entry['location'],
                    id_tocheck,
                    extra={'pos': f'L{self.linum} - {name}'},
                )
        else:
            dict_general[stem] = [dict_entry]
        if self.id2url.get(name, [url])[0] != url:
            old = name
            i = 0
            while self.id2url.get(name, [url])[0] != url:
                i += 1
                name = f'{name}_{i}' if i == 1 else f'{name[: name.rfind("_")]}_{i}'
            dict_entry['id'] = name
            logger.warning(
                '对应多重 URL，已将新的更名为 %s。',
                name,
                extra={'pos': f'L{self.linum} - {old}'},
            )
            print(f'L{self.linum} - {name} - ', end='', flush=True)
            _ = self.downloading(url, name)
        if url:
            self.id2url[name] = (url, dict_entry['meaningful'])
        return dict_general

    @staticmethod
    def prune(dict_past: DataDictInfo) -> tuple[DataDictInfo, list[dict[str, str]]]:
        dict_post: DataDictInfo = {}
        url2id: list[dict[str, str]] = []
        stem, data = next(iter(dict_past.items()))
        dict_post[stem] = []
        if not cast(bool, arg_parser().nourl):
            url2id = [
                {
                    f'url:{
                        entry["url"].replace(
                            "https://textures.minecraft.net/texture/", ""
                        )
                    }': entry['id']
                }
                for entry in data
                if entry['url']
            ]
        for entry in data:
            popped = {'url', 'meaningful'}
            if not cast(bool, arg_parser().armorstand):
                popped.add('armor_stand')
            popped.update(
                key for key, value in entry.items() if not value and value != 0
            )
            _ = [
                cast(dict[str, object], cast(object, entry)).pop(item)
                for item in popped
            ]
            dict_post[stem].append(entry)
        return dict_post, url2id

    def process(self, stem: str, data: list[str]) -> DataDictInfo:
        dict_general = {}
        for index, entry in enumerate(data):
            self.linum = str(index + 1).zfill(3)
            if not entry.strip():
                continue
            if not cast(bool, arg_parser().armorstand) and 'armor_stand' in entry:
                logger.info('盔甲架输出已关闭。', extra={'pos': f'L{self.linum}'})
                continue
            print(f'L{self.linum}', end=' - ', flush=True)
            dict_entry = self.extract(entry)
            dict_general = self.merge(dict_general, dict_entry, stem)
        print()
        return dict_general

    def info_writer(self, info: DataDictInfo) -> dict[str, str]:
        data = dumps(info, indent=4)
        duplicate: dict[str, str] = {}
        id_url = tuple(
            (name, url, meaningful) for name, (url, meaningful) in self.id2url.items()
        )
        url2canonical: dict[str, str] = {}
        for name, url, meaningful in id_url:
            if meaningful:
                url2canonical[url] = name
        for name, url, meaningful in id_url:
            if (canonical_id := url2canonical.get(url)) and name != canonical_id:
                duplicate[name] = canonical_id
                data = data.replace(f'"{name}"', f'"{canonical_id}"')
                logger.warning(
                    'URL 对应多重名称，已统一为 %s。',
                    canonical_id,
                    extra={'pos': f'{name}'},
                )
                if (duplicate_file := self.img_dir / f'{name}.png').is_file():
                    _ = duplicate_file.replace(self.img_dir / f'{canonical_id}.png')
                else:
                    logger.warning('该文件不存在，已跳过。', extra={'pos': f'{name}'})
        write_file('output/info.json', data)
        return duplicate

    @staticmethod
    def url_writer(url2id: list[dict[str, str]], duplicate: dict[str, str]) -> None:
        if cast(bool, arg_parser().nourl):
            return
        seen: set[tuple[tuple[str, str], ...]] = set()
        towrite: list[dict[str, str]] = []
        for entry in url2id:
            url, name = next(iter(entry.items()))
            if name in duplicate:
                entry[url] = duplicate[name]
            url_sorted = tuple(sorted(entry.items()))
            if url_sorted not in seen:
                seen.add(url_sorted)
                towrite.append(entry)
        with open('output/url.json', 'w', encoding='utf-8') as f:
            dump(towrite, f, indent=4)

    def __init__(self) -> None:
        self.id2url: dict[str, tuple[str, bool]] = {}
        self.img_dir: Final[Path] = Path('output/RP/textures/entity')
        self.linum: str = ''
        info_global: DataDictInfo = {}
        f = None
        url2id_global: list[dict[str, str]] = []
        if cast(bool, arg_parser().nodl):
            logger.info('跳过下载已开启。', extra={'pos': self.POS})
        else:
            self.img_dir.mkdir(parents=True, exist_ok=True)
        if cast(bool, arg_parser().nourl):
            logger.info('跳过 URL 记录已开启。', extra={'pos': self.POS})
        for f in Path('raw').glob('*.txt'):
            stem = f.stem
            with open(f, 'r', encoding='utf-8') as reading:
                data = reading.read().splitlines()
            logger.warning('%s - L%s', stem, len(data), extra={'pos': self.POS})
            info_entry, url2id_entry = Get.prune(self.process(stem, data))
            info_global |= info_entry
            if url2id_entry:
                url2id_global.extend(url2id_entry)
        if not f:
            logger.warning(
                '未在 raw 目录内找到 txt 后缀的批处理文件。', extra={'pos': self.POS}
            )
            data = [input('输入待处理项：')]
            info_global, url2id_entry = Get.prune(self.process('info', data))
            if url2id_entry:
                url2id_global.extend(url2id_entry)
        duplicate = self.info_writer(info_global)
        Get.url_writer(url2id_global, duplicate)
        logger.info('信息提取完成！', extra={'pos': self.POS})


class Identify:
    POS: Final[str] = 'IDT'

    @staticmethod
    def extract(url: str, msg: str) -> str:
        sleep(0.2)
        for i in range(3):
            try:
                response = get(
                    'https://minecraft-heads.com/custom-heads/search',
                    params={'searchterm': url},
                    timeout=(6.05, 10),
                )
                response.raise_for_status()
                break
            except exceptions.ConnectionError:
                print(f'连接错误（{i + 1}/3）...', end='', flush=True)
                sleep(1)
            except exceptions.HTTPError as e:
                data = e.response
                assert data is not None
                if 'Just a moment' in data.text:
                    raise PermissionError from e
                print(f'状态码 {data.status_code}（{i + 1}/3）...', end='', flush=True)
            except exceptions.Timeout:
                print(f'超时（{i + 1}/3）...', end='', flush=True)
                sleep(1)
        else:
            print()
            logger.error('已超时。', extra={'pos': msg})
            return ''
        data = response.text
        if 'No Heads available' in data:
            return ''
        content = data[data.find('descending') : data.find('Search Tips')]
        return Get.search_group(r'a href=.+title="([^"]+)"', content)

    @staticmethod
    def cache() -> dict[str, str]:
        if cast(bool, arg_parser().nocache):
            logger.info('缓存已忽略！', extra={'pos': 'IDT'})
            return {}
        if not Path('output/cache.json').is_file():
            return {}
        with open('output/cache.json', 'r', encoding='utf-8') as f:
            data = cast(dict[str, str], load(f))
            data_popped = [
                old_name for old_name, new_name in data.items() if not new_name
            ]
            _ = [data.pop(popped) for popped in data_popped]
            logger.info('缓存已加载！', extra={'pos': 'IDT'})
            return data

    @staticmethod
    def stripping(name: str, identifier: str) -> str:
        name = sub(r'&(#[\d]+|#x[\da-fA-F]+|[a-zA-Z]+);', '', name)
        name = name.translate(str.maketrans(' -', '__', '().#')).lower()
        name += '_' + identifier
        return name

    def process(self, data: dict[str, str], linum: str) -> None:
        url, old_name = next(iter(data.items()))
        msg = f'L{linum} - {old_name}'
        print(msg, end=' - ', flush=True)
        if (cache_name := self.mch_cache.get(old_name)) or cache_name == '':
            new_name = cache_name
            print('（缓存）', end='', flush=True)
        else:
            new_name = Identify.extract(url, msg)
            if new_name:
                self.mch_cache[old_name] = new_name
        if new_name:
            new_name = Identify.stripping(new_name, url[4:6])
            print(new_name, flush=True)
            if canonical_old := self.new2old.get(new_name):
                self.duplicate_num[new_name] = self.duplicate_num.get(new_name, 0) + 1
                cache_name = new_name
                new_name += f'_{self.duplicate_num[new_name]}'
                logger.warning(
                    '与 %s 拥有共同的新名称，已更名为 %s。',
                    canonical_old,
                    new_name,
                    extra={'pos': msg},
                )
            self.new2old[new_name] = old_name
        else:
            print(old_name, flush=True)
            new_name = old_name
            logger.warning('无可用名称。', extra={'pos': msg})
        self.info_dict.append({'old': old_name, 'new': new_name})

    def __init__(self) -> None:
        self.mch_cache: dict[str, str] = Identify.cache()
        self.info_dict: list[dict[str, str]] = []
        self.duplicate_num: dict[str, int] = {}
        self.new2old: dict[str, str] = {}
        try:
            path = 'output/url.json'
            if Path(path).is_file():
                with open(path, 'r', encoding='utf-8') as f:
                    data = cast(list[dict[str, str]], load(f))
                logger.info('%s - L%s', path, len(data), extra={'pos': self.POS})
                for i, entry in enumerate(data):
                    self.process(entry, str(i + 1).zfill(3))
                info_towrite = [[i['old'], i['new']] for i in self.info_dict]
                with open(
                    'output/name.csv', 'w', encoding='utf-8-sig', newline=''
                ) as f:
                    writing = writer(f)
                    writing.writerows(info_towrite)
            else:
                logger.error('%s 不存在！', path, extra={'pos': self.POS})
            logger.info('名称对照完成！', extra={'pos': self.POS})
        except PermissionError:
            print()
            logger.error('已触发 Turnstile！', extra={'pos': self.POS})
            if self.mch_cache:
                with open(
                    'output/name.csv', 'w', encoding='utf-8-sig', newline=''
                ) as f:
                    info_towrite = [
                        (old_name, Identify.stripping(new_name, old_name[0:2]))
                        for old_name, new_name in self.mch_cache.items()
                    ]
                    writing = writer(f)
                    writing.writerows(info_towrite)
                logger.info('已使用缓存数据生成 name.csv！', extra={'pos': self.POS})
        finally:
            with open('output/cache.json', 'w', encoding='utf-8') as f:
                dump(self.mch_cache, f, indent=4)
                logger.info('缓存已输出！', extra={'pos': self.POS})


class Import:
    POS: Final[str] = 'IMP'

    @staticmethod
    def bp_generator(name: str, template: str) -> bool:
        if not Path(template).is_file():
            return False
        with open(template, 'r', encoding='utf-8') as f:
            content = f.read()
        flag = template[template.rfind('.', 0, -7) + 1 : template.rfind('.')]
        output_path = f'output/BP/{flag}s/{name}.{flag}.json'
        content = content.replace('yzbwdlt', name)
        if flag == 'block' and name in {
            'swamp_monster',
            'swamp_monster_3d',
            'diamivore_3d',
        }:
            content = content.replace('popped', 'no_reaction')
        write_file(output_path, content)
        return True

    @staticmethod
    def rp_generator(stem2wourl: tuple[tuple[str, str], ...]) -> None:
        data: dict[str, str] = {}
        fallback = True
        if Path('templates/playerheads.csv').is_file():
            fallback = False
            with open('templates/playerheads.csv', 'r', encoding='utf-8-sig') as f:
                reading = reader(f)
                data = {i[1]: i[2] for i in reading}
        else:
            logger.warning('未找到译名文件，使用备用方案！', extra={'pos': 'IMP'})
        terrain = '\n'.join(
            f'        "player_head_{i[0]}": {{ "textures": "textures/entity/{i[0]}" }},'
            for i in stem2wourl
        )
        zhlang = (
            '\n'.join(
                f'tile.player_head:{i[0]}.name={i[1].title()} 的头' for i in stem2wourl
            )
            if fallback
            else '\n'.join(
                f'tile.player_head:{i[0]}.name={
                    data.get(i[0], i[0])[: data.get(i[0], i[0]).rfind("_")].title()
                    if "_" in {data.get(i[0], i[0])[-3], data.get(i[0], i[0])[-2]}
                    else data.get(i[0], i[1]).title()
                } 的头'
                for i in stem2wourl
            )
        )
        enlang = '\n'.join(
            f"tile.player_head:{i[0]}.name={i[1].title()}'s Head" for i in stem2wourl
        )
        terrain_towrite = (
            '{\n'
            '    "resource_pack_name": "player_head",\n'
            '    "texture_data": {\n'
            f'{terrain}\n\n'
            '        "player_head_yzbwdlt": { "textures": "textures/entity/yzbwdlt" },\n'
            '        "player_head_chthollies": { "textures": "textures/entity/chthollies" },\n'
            '        "player_head_jhy2189": { "textures": "textures/entity/jhy2189" },\n'
            '        "player_head_freamoluwu": { "textures": "textures/entity/freamoluwu" \n}'
            '    }'
            '}'
        )
        zhlang_towrite = (
            '## ===== 方块 =====\n'
            f'{zhlang}\n\n'
            'tile.player_head:yzbwdlt.name=YZBWDLT 的头\n'
            'tile.player_head:freamoluwu.name=Freamoluwu 的头\n'
            'tile.player_head:jhy2189.name=JHY2189 的头\n'
            'tile.player_head:chthollies.name=Chthollies 的头\n'
        )
        enlang_towrite = (
            '## ===== Blocks =====\n'
            f'{enlang}\n\n'
            "tile.player_head:yzbwdlt.name=YZBWDLT's Head\n"
            "tile.player_head:freamoluwu.name=Freamoluwu's Head\n"
            "tile.player_head:jhy2189.name=JHY2189's Head\n"
            "tile.player_head:chthollies.name=Chthollies's Head\n"
        )
        write_file('output/RP/textures/terrain_texture.json', terrain_towrite)
        write_file('output/RP/texts/en_US.lang', enlang_towrite)
        write_file('output/RP/texts/zh_CN.lang', zhlang_towrite)

    @staticmethod
    def info_generator() -> None:
        info_json = Path('output/info.json')
        info_js = Path('output/info.js')
        info_ts = Path('output/info.ts')
        if not info_json.is_file():
            logger.warning('未找到 info.json，跳过生成。', extra={'pos': 'IMP'})
            return
        with open(info_json, 'r', encoding='utf-8') as f:
            data = dumps(load(f)) if prettier() else f.read()
        info_js_raw = '/** 所有地图的所有头颅数据。 */\nexport const headData = '
        info_ts_raw = (
            '/** 地上头颅的数据。 */\n'
            'export interface GroundHeadData {\n'
            '    /** 头颅 ID，不含命名空间。 */\n'
            '    id: string;\n\n'
            '    /** 头颅位置，应指定为`"X Y Z"`形式。 */\n'
            '    location: string;\n\n'
            '    /** 头颅的旋转朝向。 */\n'
            '    rotation: number;\n'
            '}\n\n'
            '/** 墙上头颅的数据。 */\n'
            'export interface WallHeadData {\n'
            '    /** 头颅 ID，不含命名空间。 */\n'
            '    id: string;\n\n'
            '    /** 头颅位置，应指定为`"X Y Z"`形式。 */\n'
            '    location: string;\n\n'
            '    /** 头颅的旋转朝向。 */\n'
            '    facing: string;\n'
            '}\n\n'
            '/** 所有地图的所有头颅数据。 */\n'
            'export const headData: Record<string, (GroundHeadData | WallHeadData)[]> = '
        )
        write_file(info_js, info_js_raw + data)
        write_file(info_ts, info_ts_raw + data)
        _ = prettier([info_js.resolve(), info_ts.resolve()])

    def __init__(self) -> None:
        _ = Rename()
        block_template = 'templates/head.block.json'
        item_template = 'templates/head.item.json'
        img_dir = Path('output/RP/textures/entity')
        block_warned, item_warned = True, True
        Import.info_generator()
        stems = tuple(file.stem for file in img_dir.glob('*.png'))
        if not stems:
            logger.error('无 png 文件！', extra={'pos': self.POS})
            return
        stem2wourl: tuple[tuple[str, str], ...] = tuple(
            (stem, (stem[: stem.rfind('_')] if '_' in {stem[-3], stem[-2]} else stem))
            for stem in stems
        )
        Import.rp_generator(stem2wourl)
        if cast(bool, arg_parser().nobp):
            logger.info('跳过 blotem 生成已开启。', extra={'pos': self.POS})
        else:
            for stem, _ in stem2wourl:
                if not Import.bp_generator(stem, block_template) and block_warned:
                    logger.warning(
                        '未找到模板 %s，跳过 block 生成。',
                        block_template,
                        extra={'pos': self.POS},
                    )
                    block_warned = False
                if not Import.bp_generator(stem, item_template) and item_warned:
                    logger.warning(
                        '未找到模板 %s，跳过 item 生成。',
                        item_template,
                        extra={'pos': self.POS},
                    )
                    item_warned = False
        logger.info('导入数据生成完成！', extra={'pos': self.POS})


class Rename:
    def reading(self, path: Path) -> dict[str, tuple[str, str]]:
        with open(path, 'r', encoding='utf-8-sig') as f:
            reading = reader(f)
            names = {
                ((i[1] or i[0]) if self.revert_mode else i[0]): (
                    (i[0] if self.revert_mode else (i[1] or i[0])),
                    path.stem,
                )
                for i in reading
            }
        _ = names.pop('Column1', None)
        _ = names.pop('Column2', None)
        return names

    def read_names(self) -> dict[str, tuple[str, str]]:
        playerheads_csv = Path('templates/playerheads.csv')
        name_csv = Path('output/name.csv')
        name_list: dict[str, tuple[str, str]] = {}
        if name_csv.is_file():
            name_list.update(self.reading(name_csv))
            logger.info('工作在 name 模式下。', extra={'pos': self.pos})
        if playerheads_csv.is_file():
            name_list.update(self.reading(playerheads_csv))
            logger.info('工作在 playerheads 模式下。', extra={'pos': self.pos})
        return name_list

    def renaming(self, old_stem: str, new_stem: str, info_data: str) -> str:
        old_path = self.img_dir / f'{old_stem}.png'
        new_path = self.img_dir / f'{new_stem}.png'
        logger.info('重命名为 %s。', new_stem, extra={'pos': old_stem})
        if new_path.is_file():
            logger.warning(
                '新文件 %s 存在，已覆盖。', new_stem, extra={'pos': old_stem}
            )
        if old_path.is_file():
            _ = old_path.replace(new_path)
        else:
            logger.warning('该文件不存在，已跳过。', extra={'pos': old_stem})
        return info_data.replace(f'"{old_stem}"', f'"{new_stem}"')

    def __init__(self, revert_mode: bool = False) -> None:
        self.pos: Final[str] = 'REVERT' if revert_mode else 'RENAME'
        self.revert_mode: Final[bool] = revert_mode
        self.img_dir: Final[Path] = Path('output/RP/textures/entity')
        info_json = Path('output/info.json')
        playerheads_csv = Path('templates/playerheads.csv')
        if not (names := self.read_names()):
            logger.error('未找到名称文件，跳过重命名！', extra={'pos': self.pos})
            return
        if info_json.is_file():
            with open(info_json, 'r', encoding='utf-8') as f:
                info_data = f.read()
        else:
            logger.warning('未找到信息文件，跳过该文件！', extra={'pos': self.pos})
            info_data = ''
        stems = tuple(file.stem for file in self.img_dir.glob('*.png'))
        all_new_stems: set[str] = (
            {new_stem for new_stem, _ in self.reading(playerheads_csv).values()}
            if playerheads_csv.is_file()
            else set()
        )
        for stem in stems:
            if stem in names:
                new_stem, work_mode = names.pop(stem)
                if new_stem != stem:
                    info_data = self.renaming(stem, new_stem, info_data)
                if (
                    work_mode == 'name'
                    and playerheads_csv.is_file()
                    and new_stem not in all_new_stems
                ):
                    logger.warning(
                        '未在 playerheads 中找到对应的条目，新名称 %s。',
                        new_stem,
                        extra={'pos': stem},
                    )
            elif stem.isdecimal():
                new_stem = stem[:-1] + 'r'
                logger.warning('非法 ID，已更名为 %s。', new_stem, extra={'pos': stem})
                info_data = self.renaming(stem, new_stem, info_data)
            elif playerheads_csv.is_file() and stem not in all_new_stems:
                logger.warning('未在名称文件中找到对应的条目。', extra={'pos': stem})
        names_popped = [stem for stem, info in names.items() if info[1] == 'name']
        _ = [names.pop(item) for item in names_popped]
        if names:
            unused = '、'.join(names.keys())
            logger.warning('未使用的条目：%s。', unused, extra={'pos': self.pos})
        if info_json.is_file():
            write_file(info_json, info_data)
        logger.info('重命名完成！', extra={'pos': self.pos})


def diff() -> None:
    pos: Final[str] = 'DIFF'
    file_source, file_dest = map(Path, cast(list[str], arg_parser().files))
    if not file_source.is_file():
        logger.error('%s 文件不存在！', str(file_source), extra={'pos': pos})
        return
    if not file_dest.is_file():
        logger.error('%s 文件不存在！', str(file_dest), extra={'pos': pos})
        return
    source_suffix = file_source.suffix.lower()
    dest_suffix = file_dest.suffix.lower()
    if source_suffix != dest_suffix:
        logger.error('后缀名不一致！', extra={'pos': pos})
        return
    if not {source_suffix, dest_suffix}.issubset({'.json', '.csv'}):
        logger.error('后缀名不支持！', extra={'pos': pos})
        return
    with open(file_source, 'r', encoding='utf-8-sig') as f:
        decoded_source = load(f) if source_suffix == '.json' else tuple(reader(f))
    with open(file_dest, 'r', encoding='utf-8-sig') as f:
        decoded_dest = load(f) if dest_suffix == '.json' else tuple(reader(f))
    excluded = r"\['armor_stand'\]" if source_suffix == '.json' else r'root\[\d+\]\[2\]'
    result = DeepDiff(
        decoded_source,
        decoded_dest,
        ignore_order=True,
        exclude_regex_paths=excluded,
        verbose_level=2,
    )
    if result:
        print(result.pretty())  # pyright: ignore[reportUnknownMemberType]
        return
    logger.info('无差异。', extra={'pos': pos})


def sorting() -> None:
    pos: Final[str] = 'SORT'
    file = Path(cast(str, arg_parser().file))
    if not file.is_file():
        logger.error('文件不存在！', extra={'pos': pos})
        return
    if file.suffix.lower() != '.csv':
        logger.error('后缀名不支持！', extra={'pos': pos})
        return
    with open(file, 'r', encoding='utf-8-sig') as f:
        data = [(i[0], i[1], i[2]) for i in reader(f)]
    data.sort(key=lambda x: x[0])
    with open(file, 'w', encoding='utf-8-sig', newline='') as f:
        writing = writer(f)
        writing.writerows(data)
    logger.info('排序完成！', extra={'pos': pos})


def write_file(path: str | Path, content: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        _ = f.write(content)


def prettier(paths: list[Path] | None = None, verbose: bool = False) -> bool:
    if cast(bool, arg_parser().noprettier):
        if verbose:
            logger.info('Prettier 已关闭。', extra={'pos': __name__})
        return False
    if not (prettier_bin := which('prettier')):
        if verbose:
            logger.warning('未检测到 Prettier！', extra={'pos': __name__})
        return False
    if not paths:
        return True
    result = run(
        [prettier_bin, '--write', '--ignore-path', '[]', *map(str, paths)],
        capture_output=True,
        check=False,
        encoding='utf-8',
        text=True,
    )
    if result.returncode:
        logger.warning('Prettier 返回错误：%s', result.stderr, extra={'pos': __name__})
        return False
    return True


def arg_parser() -> Namespace:
    par = ArgumentParser(description='密室杀手自定义头颅生成器')
    subpar = par.add_subparsers(dest='cmd', required=True)
    p_get = subpar.add_parser('get', help='提取头颅信息')
    _ = p_get.add_argument(
        '-a', '--armorstand', action='store_true', help='输出盔甲架数据'
    )
    _ = p_get.add_argument('-l', '--nodl', action='store_true', help='跳过皮肤文件下载')
    _ = p_get.add_argument('-u', '--nourl', action='store_true', help='跳过 URL 记录')
    p_idt = subpar.add_parser('idt', help='获取 ID 对应的名称')
    _ = p_idt.add_argument('-e', '--nocache', action='store_true', help='忽略缓存')
    p_imp = subpar.add_parser('imp', help='生成导入数据')
    _ = p_imp.add_argument(
        '-b', '--nobp', action='store_true', help='跳过 BP 输出，即 blocks 和 items'
    )
    _ = p_imp.add_argument(
        '-p', '--noprettier', action='store_true', help='跳过 Prettier'
    )
    _ = subpar.add_parser('revert', help='回退图片命名更改')
    p_diff = subpar.add_parser('diff', help='比较两个文件')
    _ = p_diff.add_argument(
        'files', nargs=2, help='要比较的两个文件，支持 JSON 和 CSV 格式'
    )
    p_sort = subpar.add_parser('sort', help='排序文件')
    _ = p_sort.add_argument('file', help='要排序的 CSV 文件')
    args = par.parse_args()
    return args


Path('output').mkdir(parents=True, exist_ok=True)
logger = getLogger(__name__)
logger.setLevel(DEBUG)
logger.handlers.clear()
formatter = Formatter('%(pos)s - %(levelname)s - %(message)s')
file_handler = FileHandler('output/debug.log', 'w', encoding='utf-8')
stream_handler = StreamHandler()
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)
file_handler.setLevel(WARNING)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)
if __name__ == '__main__':
    try:
        match cast(
            Literal['get', 'idt', 'imp', 'revert', 'diff', 'sort'], arg_parser().cmd
        ):
            case 'get':
                _ = Get()
            case 'idt':
                _ = Identify()
            case 'imp':
                _ = Import()
            case 'revert':
                _ = Rename(True)
            case 'diff':
                diff()
            case 'sort':
                sorting()
        print()
    except AssertionError:
        pass
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception('未知错误。', extra={'pos': __name__})
    finally:
        _ = input('按回车退出...')
        shutdown()
