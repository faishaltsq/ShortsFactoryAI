import jsx from "eslint-config-next";

const config = [
  ...jsx,
  {
    ignores: [".next/**", "node_modules/**"],
  },
  {
    rules: {
      // Setiap halaman adalah client component yang mengambil data saat mount lalu
      // menyimpan hasilnya di state. Pola ini memang memanggil setState dari effect,
      // dan itu disengaja: tidak ada cache server yang bisa dipakai di console lokal ini.
      "react-hooks/set-state-in-effect": "warn",
    },
  },
];

export default config;
