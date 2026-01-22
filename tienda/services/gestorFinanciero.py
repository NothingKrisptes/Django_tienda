from decimal import Decimal
from tienda.models import ConfiguracionFiscal, ViniloMusical

class GestorFinanciero:
    
   @staticmethod
   def calcularTotalesCarrito(carrito, cupon=None):
        """
        Calcula totales del carrito.
        IMPORTANTE: Los precios ya incluyen IVA.
        """
        from tienda.models import ViniloMusical, ConfiguracionFiscal
        from decimal import Decimal
        
        items = []
        subtotal_con_iva = Decimal('0')
        
        # 1. Calcular subtotal (precios CON IVA incluido)
        for producto_id, cantidad in carrito.items():
            try:
                producto = ViniloMusical.objects.get(pk=producto_id)
                precio_con_iva = producto.obtenerPrecioFinal()  # Ya incluye IVA
                items.append({
                    'producto': producto,
                    'cantidad': cantidad,
                    'precio_aplicado': precio_con_iva,
                    'subtotal': precio_con_iva * cantidad
                })
                subtotal_con_iva += precio_con_iva * cantidad
            except ViniloMusical.DoesNotExist:
                continue
        
        # 2. Aplicar cupón de descuento (sobre el precio CON IVA)
        descuento = Decimal('0')
        if cupon:
            descuento = subtotal_con_iva * cupon.porcentajeDescuento
        
        total_con_iva = subtotal_con_iva - descuento
        
        # 3. Desglosar el IVA (para mostrar en factura)
        iva_config = ConfiguracionFiscal.obtenerIvaActual()
        factor_iva = Decimal('1') + iva_config
        
        base_imponible = total_con_iva / factor_iva  # Precio sin IVA
        monto_iva = total_con_iva - base_imponible    # Cuánto es IVA
        
        return {
            'items': items,
            'subtotal': subtotal_con_iva,       # Subtotal CON IVA
            'descuento': descuento,
            'total': total_con_iva,             # Total CON IVA
            'base_imponible': base_imponible,   # Para factura: precio sin IVA
            'impuesto': monto_iva,              # Para factura: monto de IVA
            'iva_porcentaje': float(iva_config) * 100
        }   