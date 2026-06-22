const fs = require('fs');
const path = require('path');
const PNG = require('pngjs').PNG;
const ImageTracer = require('./public/javascript/imagetracer_v1.2.1.js');
const svg2ttf = require('svg2ttf');
const SVGIcons2SVGFontStream = require('svgicons2svgfont').default || require('svgicons2svgfont');

const userId = process.argv[2];
if (!userId) {
    console.error('Usage: node generateTTF.js <userId>');
    process.exit(1);
}

// [수정됨] 사용자별 고유 디렉토리를 기본 경로로 설정
const baseDir = path.join(__dirname, 'FONT', userId.toString());
const flippedDir = path.join(baseDir, 'flipped_result');
const svgDir = path.join(baseDir, 'svg');
const svgFontsDir = path.join(baseDir, 'svg_fonts');
const ttfDir = path.join(baseDir, 'ttf_fonts');

// 필요한 디렉토리 생성
// recursive: true 옵션 덕분에 FONT/<userId>/flipped_result 같은 중첩 경로도 한 번에 생성됩니다.
[baseDir, flippedDir, svgDir, svgFontsDir, ttfDir].forEach(dir => {
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
});

// PNG 파일 목록 가져오기
// 이제 FONT/<userId>/flipped_result/ 에서 파일을 읽어옵니다.
const files = fs.readdirSync(flippedDir).filter(f => f.endsWith('.png'));

const option = {
    ltres: 1,
    qtres: 1,
    strokewidth: 0.5,
    pathomit: 8,
    blurradius: 0,
    blurdelta: 10,
    pal: [{ r: 0, g: 0, b: 0, a: 255 }, { r: 255, g: 255, b: 255, a: 255 }],
    linefilter: true
};

async function generateFont(userId) {
    const fontName = `user_font_${userId}`;

    // PNG → SVG 변환
    for (const file of files) {
        const fileName = path.basename(file, '.png');
        const pngPath = path.join(flippedDir, file);
        const svgPath = path.join(svgDir, `${fileName}.svg`);

        const data = fs.readFileSync(pngPath);
        const png = PNG.sync.read(data);

        const myImageData = { width: png.width, height: png.height, data: png.data };
        const svgString = ImageTracer.imagedataToSVG(myImageData, option);

        fs.writeFileSync(svgPath, svgString);
        console.log(`Converted ${file} to SVG`);
    }

    // SVG 폰트 스트림 생성
    const fontStream = new SVGIcons2SVGFontStream({
        fontName: fontName,
        normalize: true,
        fontHeight: 1000,
        centerHorizontally: true,
        centerVertically: true,
        descent: 200,
    });
    
    // [경로 수정됨] 모든 경로는 사용자별 디렉토리 하위에 생성됩니다.
    const svgFontPath = path.join(svgFontsDir, 'font_temp.svg');
    const ttfOutputPath = path.join(ttfDir, `${fontName}.ttf`);

    const writeStream = fs.createWriteStream(svgFontPath);
    fontStream.pipe(writeStream);

    for (const file of files) {
        const fileName = path.basename(file, '.png');
        const svgPath = path.join(svgDir, `${fileName}.svg`);

        let codePoint = 0x20; // 기본값은 스페이스
        const match = fileName.match(/inferred_(.+)/);
        if (match) {
            const hexStr = match[1];
            codePoint = parseInt(hexStr, 16);
            if (isNaN(codePoint)) codePoint = 0x20;
        }

        const glyphStream = fs.createReadStream(svgPath);
        glyphStream.metadata = {
            unicode: [String.fromCodePoint(codePoint)],
            name: `uni${codePoint.toString(16).toUpperCase()}`
        };

        fontStream.write(glyphStream);
        console.log(`Added glyph for code point U+${codePoint.toString(16).toUpperCase()}`);
    }

    fontStream.end();

    writeStream.on('finish', () => {
        try {
            // SVG font -> glyph TTF. Name-table / OS-2 metadata (incl. the Korean
            // family name) is applied afterwards by set_font_metadata.py (fonttools),
            // which is far more reliable than opentype.js for Hangul.
            const svgFontData = fs.readFileSync(svgFontPath, 'utf8');
            const ttf = svg2ttf(svgFontData, {});
            fs.writeFileSync(ttfOutputPath, Buffer.from(ttf.buffer));
            console.log(`TTF font generated at: ${ttfOutputPath}`);

            // 임시 SVG 폰트 파일 삭제
            fs.unlinkSync(svgFontPath);
            console.log(`Cleaned up temporary SVG font file: ${svgFontPath}`);
        } catch (err) {
            console.error('❌ Error during TTF generation:', err);
            process.exitCode = 1;
        }
    });

    writeStream.on('error', (err) => {
        console.error('Error writing SVG font:', err);
    });
}

generateFont(userId).catch(console.error);