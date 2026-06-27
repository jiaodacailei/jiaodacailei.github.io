(function () {
  const script = document.currentScript;
  const base = (script && script.getAttribute('data-base')) || '../../images/';

  // w/h = display size tuned to each photo's actual aspect ratio
  // pos  = object-position to keep the face in frame
  const PHOTOS = [
    { file: 'photo-1.jpg', w: 128, h: 170, pos: 'center 8%'    }, // portrait upper-body ~3:4
    { file: 'photo-2.jpg', w: 112, h: 186, pos: 'center 8%'    }, // tall full-body ~3:5
    { file: 'photo-3.jpg', w: 128, h: 170, pos: 'center 10%'   }, // three-quarter ~3:4
    { file: 'life-1.jpg',  w: 200, h: 150, pos: 'center center' }, // landscape 4:3
    { file: 'life-2.jpg',  w: 112, h: 200, pos: 'center 12%'   }, // portrait selfie ~9:16
  ];

  function init() {
    const p = PHOTOS[Math.floor(Math.random() * PHOTOS.length)];

    if (!document.getElementById('fp-style')) {
      const s = document.createElement('style');
      s.id = 'fp-style';
      s.textContent = `
        @keyframes fp-float {
          0%, 100% { transform: translateY(0px);
                     box-shadow: 0 8px 28px rgba(0,0,0,.22), 0 2px 6px rgba(0,0,0,.12); }
          50%       { transform: translateY(-10px);
                     box-shadow: 0 20px 52px rgba(0,0,0,.28), 0 6px 16px rgba(0,0,0,.14); }
        }
        .fp-card {
          animation: fp-float 4.5s ease-in-out infinite;
          transition: transform .2s, box-shadow .2s;
        }
        .fp-card:hover { animation-play-state: paused; transform: scale(1.04) translateY(-4px); }
        .fp-close {
          position: absolute; top: 6px; right: 6px;
          width: 22px; height: 22px; border-radius: 50%;
          background: rgba(0,0,0,.48); color: #fff; border: none;
          font-size: 16px; line-height: 1; cursor: pointer; padding: 0;
          display: flex; align-items: center; justify-content: center;
          opacity: 0; transition: opacity .2s;
        }
        .fp-card:hover .fp-close { opacity: 1; }
        .fp-label {
          position: absolute; bottom: 0; left: 0; right: 0;
          background: linear-gradient(transparent, rgba(0,0,0,.58));
          color: #fff; font-size: 11px; font-weight: 700;
          padding: 20px 8px 7px; letter-spacing: .05em;
          font-family: -apple-system, 'Noto Sans SC', sans-serif;
        }
      `;
      document.head.appendChild(s);
    }

    const card = document.createElement('div');
    card.className = 'fp-card';
    Object.assign(card.style, {
      position:     'fixed',
      right:        '20px',
      bottom:       '88px',
      zIndex:       '55',
      borderRadius: '12px',
      overflow:     'hidden',
      width:        p.w + 'px',
      background:   '#fff',
      cursor:       'default',
    });

    const img = document.createElement('img');
    img.src = base + p.file;
    img.alt = '蔡磊';
    Object.assign(img.style, {
      display:        'block',
      width:          p.w + 'px',
      height:         p.h + 'px',
      objectFit:      'cover',
      objectPosition: p.pos,
    });

    const label = document.createElement('div');
    label.className = 'fp-label';
    label.textContent = '📸 蔡磊';

    const close = document.createElement('button');
    close.className = 'fp-close';
    close.innerHTML  = '×';
    close.title      = '关闭';
    close.onclick    = () => card.remove();

    card.appendChild(img);
    card.appendChild(label);
    card.appendChild(close);
    document.body.appendChild(card);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
