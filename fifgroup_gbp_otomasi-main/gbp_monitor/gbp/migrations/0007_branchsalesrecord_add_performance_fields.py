from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gbp', '0006_add_branch_sales_record'),
    ]

    operations = [
        migrations.AddField(
            model_name='branchsalesrecord',
            name='osa',
            field=models.FloatField(
                blank=True, null=True,
                verbose_name='OSA (Unit)',
                help_text='NSA dalam Unit. Jumlah kontrak/kendaraan yang dibiayai.',
            ),
        ),
        migrations.AddField(
            model_name='branchsalesrecord',
            name='cd',
            field=models.FloatField(
                blank=True, null=True,
                verbose_name='CD (%)',
                help_text='Cycle Delinquent dalam persen. Contoh: 95.20',
            ),
        ),
        migrations.AddField(
            model_name='branchsalesrecord',
            name='profit',
            field=models.FloatField(
                blank=True, null=True,
                verbose_name='Profit (Rupiah)',
                help_text='Profit cabang dalam Rupiah. Bisa positif atau negatif.',
            ),
        ),
        migrations.AlterField(
            model_name='branchsalesrecord',
            name='nl',
            field=models.FloatField(
                blank=True, null=True,
                verbose_name='NL (Nett Losses)',
                help_text='Nett Losses. Bisa dalam Rupiah atau persentase tergantung konteks upload.',
            ),
        ),
    ]
