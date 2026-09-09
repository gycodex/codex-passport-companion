// components/bsp/src/bsp_battery.c
// 移植自 trae_card/components/platform/platform_esp32/src/battery_cw2017.c
// (去掉了电池 profile 写入部分:开源硬件用户电池各异,用芯片自带 Li-Poly profile 更通用)
#include "bsp_battery.h"
#include "bsp_i2c.h"
#include "bsp_pins.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "bsp_batt";

#define CW_REG_VERSION   0x00   // 版本号,上电应答即代表芯片在位
#define CW_REG_VCELL_H   0x02   // 14bit 电压,V(uV) = raw * 312.5
#define CW_REG_SOC_H     0x04   // 高字节 = 整数百分比;低字节(0x05)= 1/256 %
#define CW_REG_CONFIG    0x08   // 0xF0=睡眠 / 0x30=复位态 / 0x00=正常
#define CW_READY_RETRIES 100
#define CW_READY_DELAY_MS 100

static i2c_master_dev_handle_t s_dev;

static int cw_read(uint8_t reg, uint8_t *buf, size_t n) {
    if (!s_dev) return -1;
    return i2c_master_transmit_receive(s_dev, &reg, 1, buf, n, 100) == ESP_OK ? 0 : -1;
}

static int cw_write(uint8_t reg, uint8_t val) {
    if (!s_dev) return -1;
    uint8_t b[2] = { reg, val };
    return i2c_master_transmit(s_dev, b, 2, 100) == ESP_OK ? 0 : -1;
}

esp_err_t bsp_battery_init(void) {
    if (s_dev) return ESP_OK;

    esp_err_t e = bsp_i2c_init();
    if (e != ESP_OK) return e;

    i2c_device_config_t dc = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address  = BSP_I2C_CW2017_ADDR,
        .scl_speed_hz    = 100000,
    };
    e = i2c_master_bus_add_device(bsp_i2c_bus(), &dc, &s_dev);
    if (e != ESP_OK) { ESP_LOGE(TAG, "添加 I2C 设备失败: %s", esp_err_to_name(e)); return e; }

    uint8_t ver = 0;
    if (cw_read(CW_REG_VERSION, &ver, 1) != 0) {
        ESP_LOGW(TAG, "CW2017 未应答 —— 用 bsp_i2c_scan() 确认 0x%02X 是否在线;"
                      "无电量计的板子可忽略本项", BSP_I2C_CW2017_ADDR);
        i2c_master_bus_rm_device(s_dev);
        s_dev = NULL;
        return ESP_ERR_NOT_FOUND;
    }
    ESP_LOGI(TAG, "检测到 CW2017 VERSION=0x%02X", ver);

    // 数据手册要求按 0x30 -> 0x00 的顺序退出睡眠/复位态并重新开始计算。
    // 只写 0x00 时，部分批次会一直返回无效 SOC（0xFF）。
    if (cw_write(CW_REG_CONFIG, 0x30) != 0) {
        ESP_LOGE(TAG, "CW2017 进入复位态失败");
        return ESP_FAIL;
    }
    vTaskDelay(pdMS_TO_TICKS(20));
    if (cw_write(CW_REG_CONFIG, 0x00) != 0) {
        ESP_LOGE(TAG, "CW2017 启动计算失败");
        return ESP_FAIL;
    }

    for (int attempt = 0; attempt < CW_READY_RETRIES; ++attempt) {
        uint8_t soc[2] = {0};
        if (cw_read(CW_REG_SOC_H, soc, sizeof(soc)) == 0 && soc[0] <= 100) {
            ESP_LOGI(TAG, "CW2017 电量就绪 SOC=%u.%u%%", soc[0],
                     ((unsigned)soc[1] * 100U) / 256U);
            return ESP_OK;
        }
        vTaskDelay(pdMS_TO_TICKS(CW_READY_DELAY_MS));
    }

    ESP_LOGW(TAG, "CW2017 首次电量计算超时，将在后台继续重试");

    return ESP_OK;
}

int bsp_battery_soc(void) {
    uint8_t b[2] = { 0 };
    if (cw_read(CW_REG_SOC_H, b, 2) != 0) {
        ESP_LOGD(TAG, "读取 SOC 寄存器失败");
        return -1;
    }
    int soc = b[0];                       // 高字节即整数百分比
    if (soc > 100) {
        ESP_LOGD(TAG, "SOC 寄存器尚未就绪: %02X %02X", b[0], b[1]);
        return -1;
    }
    return soc;
}

int bsp_battery_mv(void) {
    uint8_t b[2] = { 0 };
    if (cw_read(CW_REG_VCELL_H, b, 2) != 0) {
        ESP_LOGD(TAG, "读取电池电压寄存器失败");
        return -1;
    }
    uint32_t raw = ((uint32_t)b[0] << 8 | b[1]) & 0x3FFF;   // 14bit
    return (int)((raw * 3125) / 10000);                     // raw * 312.5uV → mV
}
