from json import dump, load
from logging import shutdown
from pathlib import Path
from shutil import copy2
from typing import Final, TypedDict, cast

from PIL import Image

from mm_head import logger, write_file


class TextureInfo(TypedDict):
    resource_pack_name: str
    texture_data: dict[str, dict[str, str]]


class Painting:
    POS: Final[str] = 'PAINTING'

    def crop(self, path: Path) -> bool:
        pos = 'CROP'
        stem = path.stem
        with Image.open(path) as f:
            width, height = f.size
            if width % 16 or height % 16:
                logger.error('尺寸错误！', extra={'pos': f'{pos} - {stem}'})
                return False
            width_mark, height_mark = width // 16, height // 16
            logger.info(
                '%sx%s', width_mark, height_mark, extra={'pos': f'{pos} - {stem}'}
            )
            Painting.bp_generator(
                self.path_map['template']['replacer'],
                self.path_map['output_dir']['item'],
                stem,
                f'{width_mark}{height_mark}',
            )
            self.texture_json['texture_data'][stem] = {
                'textures': f'textures/painting/{stem}_replacer'
            }
            for w in range(width_mark):
                for h in range(height_mark):
                    h_real = height_mark - 1 - h
                    location = f'{w}{h_real}'
                    tile_name = f'{stem}_{location}'
                    tile = f.crop((w * 16, h * 16, (w + 1) * 16, (h + 1) * 16))
                    tile.save(
                        self.path_map['output_dir']['painting'] / f'{tile_name}.png'
                    )
                    Painting.bp_generator(
                        self.path_map['template']['block'],
                        self.path_map['output_dir']['block'],
                        stem,
                        location,
                    )
                    Painting.bp_generator(
                        self.path_map['template']['item'],
                        self.path_map['output_dir']['item'],
                        stem,
                        location,
                    )
                    self.texture_json['texture_data'][tile_name] = {
                        'textures': f'textures/painting/{tile_name}'
                    }
        return True

    @staticmethod
    def bp_generator(
        template: Path, output_dir: Path, stem: str, location: str
    ) -> None:
        replacer = 'replacer' in template.stem
        file_name = f'{stem}_replacer' if replacer else f'{stem}_{location}'
        table = {
            '(id)': stem,
            '(location)': location,
            '(length)': location[0],
            '(height)': location[1],
        }
        str_template = str(template)
        flag = str_template[
            str_template.rfind('.', 0, -7) + 1 : str_template.rfind('.')
        ]
        with open(template, 'r', encoding='utf-8') as f:
            data = f.read()
        if replacer:
            data = data.replace(
                '"minecraft:icon": "(id)",', f'"minecraft:icon": "{stem}_replacer",'
            )
        for old, new in table.items():
            data = data.replace(old, new)
        write_file(output_dir / stem / f'{file_name}.{flag}.json', data)

    def __init__(self) -> None:
        self.enlang: list[str] = ['## ===== Items =====', '']
        self.texture_json: TextureInfo = {
            'resource_pack_name': 'painting',
            'texture_data': {
                'background': {'textures': 'textures/painting/background'},
            },
        }
        self.path_map: dict[str, dict[str, Path]] = {
            'template': {
                'block': Path('templates/painting.block.json'),
                'item': Path('templates/painting.item.json'),
                'replacer': Path('templates/painting_replacer.item.json'),
            },
            'input': {
                'json': Path('raw_painting/vanillaPaintingData.json'),
                'painting': Path('raw_painting'),
            },
            'output_dir': {
                'block': Path('output/BP_custom_painting/blocks/painting'),
                'item': Path('output/BP_custom_painting/items/painting'),
                'painting': Path('output/RP_custom_painting/textures/painting'),
            },
            'output_file': {
                'enlang': Path('output/RP_custom_painting/texts/en_US.lang'),
                'texture': Path(
                    'output/RP_custom_painting/textures/terrain_texture.json'
                ),
            },
        }
        for path in self.path_map['template'].values():
            if not path.is_file():
                logger.error('模板不存在！', extra={'pos': f'{self.POS} - {path.name}'})
                return
        if not (data_json := self.path_map['input']['json']).is_file():
            logger.error(
                '译名不存在！', extra={'pos': f'{self.POS} - {data_json.name}'}
            )
            return
        for path in self.path_map['output_dir'].values():
            path.mkdir(parents=True, exist_ok=True)
        with open(data_json, 'r', encoding='utf-8') as f:
            lang_json = cast(list[dict[str, str]], load(f))
            lang_dict = {entry['id'].lower(): entry['name'] for entry in lang_json}
        for painting in Path(self.path_map['input']['painting']).glob('*.png'):
            stem = painting.stem
            _ = copy2(
                painting,
                self.path_map['output_dir']['painting'] / f'{stem}_replacer.png',
            )
            self.enlang.append(f'item.painting:{stem}.name={lang_dict.get(stem, stem)}')
            if stem not in lang_dict:
                logger.warning('无译名。', extra={'pos': f'{self.POS} - {stem}'})
            _ = self.crop(painting)
        with open(
            self.path_map['output_file']['texture'],
            'w',
            encoding='utf-8',
        ) as f:
            dump(self.texture_json, f, indent=4)
        _ = copy2(
            self.path_map['output_file']['texture'],
            self.path_map['output_file']['texture'].parent / 'item_texture.json',
        )
        self.enlang.append('')
        write_file(self.path_map['output_file']['enlang'], '\n'.join(self.enlang))
        logger.info('输出完成！', extra={'pos': self.POS})


if __name__ == '__main__':
    try:
        _ = Painting()
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception('未知错误。', extra={'pos': __name__})
    finally:
        _ = input('按回车退出...')
        shutdown()
